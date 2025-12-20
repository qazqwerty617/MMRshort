"""
Signal Generator - генерация торговых сигналов на шорт
ОПТИМИЗИРОВАННАЯ ВЕРСИЯ с Funding Rate, MTF, Whale Tracking
"""

from typing import Dict, List, Optional
from indicators import TechnicalIndicators
from divergence_detector import DivergenceDetector
from volume_analyzer import VolumeAnalyzer
from orderbook_analyzer import OrderbookAnalyzer
from coin_profiler import CoinProfiler
from funding_rate_analyzer import FundingRateAnalyzer
from multi_timeframe_analyzer import MultiTimeframeAnalyzer
from dex_analyzer import DexAnalyzer
from logger import get_logger

logger = get_logger()


class SignalGenerator:
    """Класс для генерации сигналов на вход в шорт"""
    
    def __init__(self, config: Dict, coin_profiler: CoinProfiler):
        """
        Инициализация генератора
        
        Args:
            config: Конфигурация из config.yaml
            coin_profiler: Экземпляр профайлера монет
        """
        self.config = config['signal']
        self.short_config = config['short_entry']
        self.coin_profiler = coin_profiler
        
        # Инициализация анализаторов
        self.indicators = TechnicalIndicators()
        self.divergence_detector = DivergenceDetector()
        self.volume_analyzer = VolumeAnalyzer(config['short_entry'])
        self.orderbook_analyzer = OrderbookAnalyzer(config['short_entry'])
        self.mtf_analyzer = MultiTimeframeAnalyzer()
        self.dex_analyzer = DexAnalyzer()  # DEX анализатор
        
        # Кэш для предыдущих ордербуков (для whale tracking)
        self.previous_orderbooks = {}
        logger.info("✅ Signal Generator v2.0 (No Limits) loaded")
    
    async def generate_signal(self, symbol: str, pump_data: Dict,
                             price_history: List[float],
                             volume_history: List[float],
                             klines: List[Dict],
                             orderbook: Optional[Dict] = None,
                             mexc_client = None) -> Optional[Dict]:
        """
        Сгенерировать сигнал на шорт
        
        Args:
            symbol: Символ пары
            pump_data: Данные о пампе
            price_history: История цен
            volume_history: История объёмов
            klines: Список свечей с OHLCV данными
            orderbook: Ордербук (опционально)
            mexc_client: MEXC клиент для funding rate и MTF анализа
            
        Returns:
            Данные сигнала или None
        """
        logger.info(f"🔍 {symbol}: Начинаю анализ для SHORT сигнала (памп: +{pump_data['increase_pct']:.2f}%)")
        
        if len(price_history) < 2:
            logger.warning(f"❌ {symbol}: Критически мало данных (price_history={len(price_history)})")
            return None
        
        current_price = price_history[-1]
        logger.debug(f"   Текущая цена: {current_price:.8f}")
        
        # 1. Рассчитываем технические индикаторы
        rsi = self.indicators.calculate_rsi(price_history, self.short_config['rsi_period'])
        macd = self.indicators.calculate_macd(price_history)
        
        if rsi is None:
            logger.warning(f"⚠️ {symbol}: Не удалось рассчитать RSI (мало данных), использую 50.0")
            rsi = 50.0
            
        if macd is None:
            logger.warning(f"⚠️ {symbol}: Не удалось рассчитать MACD (мало данных), использую 0.0")
            macd = {'macd': 0.0, 'signal': 0.0, 'histogram': 0.0}
            
        # if rsi is None or macd is None:
        #     logger.warning(f"❌ {symbol}: Не удалось рассчитать индикаторы (RSI={rsi}, MACD={macd})")
        #     return None
        
        logger.info(f"📈 {symbol}: RSI={rsi:.1f}, MACD={macd['macd']:.6f}")
        
        # 2. Проверяем дивергенцию
        macd_values = []
        for i in range(min(50, len(price_history))):
            macd_hist = self.indicators.calculate_macd(price_history[:-(50-i)] if i > 0 else price_history)
            if macd_hist:
                macd_values.append(macd_hist['macd'])
        
        divergence_score = self.divergence_detector.calculate_divergence_score(
            price_history[-50:],
            [rsi] * len(price_history[-50:]),
            macd_values if macd_values else None
        )
        
        logger.info(f"📉 {symbol}: Divergence Score = {divergence_score:.1f}/10")
        
        # 3. Анализируем падение объёма
        volume_drop = self.volume_analyzer.detect_volume_drop(volume_history)
        volume_score = self.volume_analyzer.calculate_volume_score(volume_history)
        
        if not volume_drop or not volume_drop['is_significant']:
            if volume_drop:
                logger.warning(f"⚠️ {symbol}: Объём упал недостаточно: {volume_drop['volume_drop_pct']:.1f}% (мин: {self.volume_analyzer.min_volume_drop}%), но продолжаем анализ...")
            else:
                logger.warning(f"⚠️ {symbol}: Не удалось рассчитать падение объёма, продолжаем анализ...")
            # return None  <-- УБРАЛИ ЖЕСТКИЙ ВЫХОД
        
        logger.info(f"✅ {symbol}: Объём упал на {volume_drop['volume_drop_pct']:.1f}% (score: {volume_score:.1f}/10)")
        
        # 4. Анализируем ордербук и whale activity
        orderbook_score = 0.0
        orderbook_analysis = None
        resistance_price = None
        whale_data = None
        
        if orderbook:
            orderbook_analysis = self.orderbook_analyzer.analyze_orderbook(orderbook, current_price)
            orderbook_score = self.orderbook_analyzer.calculate_orderbook_score(
                orderbook_analysis, current_price
            )
            resistance_price = self.orderbook_analyzer.find_nearest_resistance(
                orderbook_analysis, current_price
            )
            
            # Whale tracking
            prev_orderbook = self.previous_orderbooks.get(symbol)
            whale_data = self.orderbook_analyzer.track_whale_activity(orderbook, prev_orderbook)
            self.previous_orderbooks[symbol] = orderbook
        
        # 5. Funding Rate анализ
        funding_score = 0.0
        funding_data = None
        if mexc_client:
            funding_analyzer = FundingRateAnalyzer(mexc_client)
            funding_data = await funding_analyzer.get_funding_rate(symbol)
            funding_score = funding_analyzer.calculate_funding_score(funding_data)
        
        # 6. Multi-Timeframe анализ
        mtf_score = 0.0
        mtf_data = None
        if mexc_client:
            mtf_data = await self.mtf_analyzer.analyze_trend(mexc_client, symbol)
            mtf_score = self.mtf_analyzer.calculate_mtf_score(mtf_data)
        
        # 7. DEX vs CEX анализ - КЛЮЧЕВОЙ ФАКТОР!
        dex_score = 0.0
        dex_data = None
        dex_spread_data = None
        
        dex_data = await self.dex_analyzer.get_dex_price(symbol)
        if dex_data:
            dex_spread_data = self.dex_analyzer.calculate_cex_dex_spread(current_price, dex_data['price'])
            dex_score = dex_spread_data['spread_score']
            
            if dex_spread_data['is_overvalued_on_cex']:
                logger.warning(f"🔥 {symbol}: CEX переоценена! Спред: +{dex_spread_data['spread_pct']:.2f}% (CEX: ${current_price:.6f} > DEX: ${dex_data['price']:.6f})")
            else:
                logger.info(f"ℹ️ {symbol}: DEX дороже на {abs(dex_spread_data['spread_pct']):.2f}%")
        
        # 8. Получаем веса - АДАПТИВНЫЕ в зависимости от типа пампа
        pump_type = pump_data.get('pump_type', '')
        
        if pump_type in ['MASSIVE', 'FAST_IMPULSE']:
            # Для быстрых/массивных пампов: приоритет DEX и объемы!
            weights = {
                'divergence': 0.10,      # Снижен с ~0.25
                'volume_drop': 0.30,     # Увеличен! (было ~0.25)
                'orderbook': 0.10,       # Снижен с ~0.25
                'rsi_level': 0.10,       # Снижен с ~0.25
                'dex_spread': 0.40       # МАКСИМУМ! (новое)
            }
            logger.info(f"🎯 {symbol}: Используются адаптивные веса для {pump_type} (приоритет: DEX 40%, Объемы 30%)")
        else:
            # Обычные веса
            weights = self.coin_profiler.get_weights_for_coin(symbol)
        
        # 9. Рассчитываем общий score качества
        base_score = (
            divergence_score * weights['divergence'] +
            volume_score * weights['volume_drop'] +
            orderbook_score * weights['orderbook'] +
            (max(0, rsi - 50) / 50 * 10) * weights['rsi_level']
        )
        
        # БОНУСЫ от новых факторов
        bonus_score = 0.0
        if funding_score > 0:
            bonus_score += (funding_score / 10) * 1.0
        if mtf_score > 0:
            bonus_score += (mtf_score / 10) * 1.0
        if whale_data:
            whale_score = whale_data.get('whale_score', 0)
            bonus_score += (whale_score / 10) * 1.0
        
        # 🔥 DEX СПРЕД - МОЩНЫЙ БОНУС (увеличен для быстрых/массивных пампов)!
        if dex_score > 0:
            if pump_type in ['MASSIVE', 'FAST_IMPULSE']:
                dex_bonus = (dex_score / 10) * 4.0  # До +4.0 для быстрых пампов!
                logger.warning(f"💎💎 {symbol}: DEX бонус +{dex_bonus:.1f} к качеству (приоритетный режим)!")
            else:
                dex_bonus = (dex_score / 10) * 2.0  # До +2.0 для обычных
                logger.warning(f"💎 {symbol}: DEX бонус +{dex_bonus:.1f} к качеству!")
            bonus_score += dex_bonus
        
        quality_score = base_score + bonus_score
        display_score = min(quality_score, 10.0)
        
        logger.info(f"📊 {symbol}: Quality Score = {quality_score:.2f} (база: {base_score:.2f} + бонус: {bonus_score:.2f})")
        logger.info(f"   Факторы: div={divergence_score:.1f}, vol={volume_score:.1f}, ob={orderbook_score:.1f}, rsi={rsi:.0f}")
        logger.info(f"   Веса: div={weights['divergence']:.2f}, vol={weights['volume_drop']:.2f}, ob={weights['orderbook']:.2f}, rsi={weights['rsi_level']:.2f}")
        
        if quality_score < self.config['min_quality_score']:
            logger.warning(f"❌ {symbol}: Качество {quality_score:.2f} < минимум {self.config['min_quality_score']:.1f}")
            return None
        
        # 9. Определяем точку входа
        entry_price = resistance_price if resistance_price else current_price
        logger.info(f"💰 {symbol}: Вход @ {entry_price:.8f}")
        
        # 10. Рейтинг надёжности монеты
        reliability = self.coin_profiler.get_coin_reliability(symbol)
        
        # Формируем сигнал
        signal = {
            "symbol": symbol,
            "entry_price": entry_price,
            "quality_score": display_score,
            "raw_quality_score": quality_score,
            "reliability_score": reliability,
            "factors": {
                "divergence_score": divergence_score,
                "volume_drop_pct": volume_drop['volume_drop_pct'],
                "orderbook_score": orderbook_score,
                "rsi_value": rsi,
                "funding_score": funding_score,
                "mtf_score": mtf_score,
                "whale_score": whale_data.get('whale_score', 0) if whale_data else 0,
                "dex_score": dex_score,  # DEX фактор
                "dex_spread_pct": dex_spread_data.get('spread_pct', 0) if dex_spread_data else 0
            },
            "weights": weights,
            "pump_increase_pct": pump_data['increase_pct'],
            "current_price": current_price,
            "orderbook_analysis": orderbook_analysis,
            "funding_data": funding_data,
            "mtf_data": mtf_data,
            "whale_data": whale_data,
            "dex_data": dex_data,  # Данные DEX
            "dex_spread": dex_spread_data  # Спред CEX/DEX
        }
        
        logger.warning(f"🎯✅ SHORT СИГНАЛ СГЕНЕРИРОВАН: {symbol} @ {entry_price:.8f}")
        logger.warning(f"   Качество: {display_score:.1f}/10 (база: {base_score:.2f} + бонус: {bonus_score:.2f})")
        logger.warning(f"   Надёжность: {reliability:.1f}/10")
        
        return signal
    
    def format_signal_message(self, signal: Dict) -> str:
        """Форматировать сигнал для Telegram"""
        symbol = signal['symbol']
        entry = signal['entry_price']
        quality = signal['quality_score']
        reliability = signal['reliability_score']
        factors = signal['factors']
        
        msg = f"""
🎯 **СИГНАЛ НА ШОРТ**

**Пара:** `{symbol}`
**Вход:** `{entry:.8f}`

📊 **Анализ:**
"""
        
        # Дивергенция
        div_score = factors['divergence_score']
        if div_score >= 7:
            msg += "✅ Медвежья дивергенция (сильная)\n"
        elif div_score >= 4:
            msg += "✅ Медвежья дивергенция (средняя)\n"
        elif div_score > 0:
            msg += "⚠️ Медвежья дивергенция (слабая)\n"
        
        # Объём
        vol_drop = factors['volume_drop_pct']
        msg += f"{'✅' if vol_drop >=60 else '⚠️'} Объём падает -{vol_drop:.0f}%\n"
        
        # Ордербук
        ob_score = factors['orderbook_score']
        if ob_score >= 7:
            msg += "✅ Сильное сопротивление в ордербуке\n"
        elif ob_score >= 4:
            msg += "⚠️ Среднее сопротивление\n"
        
        # RSI
        rsi = factors['rsi_value']
        if rsi >= 70:
            msg += f"✅ RSI перекуплен ({rsi:.0f})\n"
        
        # Funding Rate
        funding_score = factors.get('funding_score', 0)
        if funding_score > 0 and signal.get('funding_data'):
            funding_pct = signal['funding_data'].get('funding_rate_pct', 0)
            if funding_pct >= 0.10:
                msg += f"🔥 Funding rate очень высокий ({funding_pct:.4f}%)\n"
            elif funding_pct >= 0.05:
                msg += f"✅ Funding rate высокий ({funding_pct:.4f}%)\n"
        
        # Multi-Timeframe
        mtf_score = factors.get('mtf_score', 0)
        if mtf_score > 0 and signal.get('mtf_data'):
            mtf_data = signal['mtf_data']
            if mtf_data.get('overall_bearish'):
                trend_1h = mtf_data.get('1h_trend', '')
                trend_4h = mtf_data.get('4h_trend', '')
                msg += f"📉 MTF: 1ч={trend_1h}, 4ч={trend_4h} (медвежий тренд)\n"
        
        # Whale Activity
        whale_score = factors.get('whale_score', 0)
        if whale_score > 0 and signal.get('whale_data'):
            whale_data = signal['whale_data']
            if whale_data.get('whale_sells_appeared'):
                msg += "🐋 Появились крупные стены продаж\n"
            if whale_data.get('whale_buys_disappeared'):
                msg += "🐋 Buy support исчез\n"
        
        # 🔥 DEX vs CEX Spread - КЛЮЧЕВОЙ СИГНАЛ!
        dex_score = factors.get('dex_score', 0)
        dex_spread_pct = factors.get('dex_spread_pct', 0)
        
        # Блок DEX Info (всегда, если есть данные)
        if signal.get('dex_data'):
            dex_info = signal['dex_data']
            msg += f"\n🦄 **DEX Info:**\n"
            msg += f"   Цена: ${dex_info['price']:.6f} ({dex_info['dex_name']})\n"
            msg += f"   📈 [DexScreener](https://dexscreener.com/{dex_info['chain']}/{dex_info['dex_name']})\n"
            
            if dex_spread_pct > 0:
                 msg += f"   🔥 **Спред: +{dex_spread_pct:.2f}%** (CEX дороже)\n"
            elif dex_spread_pct < 0:
                 msg += f"   ❄️ Спред: {dex_spread_pct:.2f}% (DEX дороже)\n"
        
        msg += f"\n⭐ **Качество сигнала:** `{quality:.1f}/10`\n"
        
        raw_quality = signal.get('raw_quality_score', quality)
        if raw_quality > quality:
            bonus = raw_quality - quality
            msg += f"   _(базовый: {quality:.1f}/10 + бонус: +{bonus:.1f})_\n"
        
        msg += f"🎲 **Надёжность монеты:** `{reliability:.1f}/10`\n"
        msg += f"\n_Памп: +{signal['pump_increase_pct']:.1f}%_"
        
        return msg
