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
from open_interest_analyzer import OpenInterestAnalyzer
from historical_pattern_analyzer import HistoricalPatternAnalyzer
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
        self.dex_analyzer = DexAnalyzer()
        self.oi_analyzer = OpenInterestAnalyzer()  # Open Interest
        self.pattern_analyzer = HistoricalPatternAnalyzer()  # Исторические паттерны
        
        # Кэш для предыдущих ордербуков (для whale tracking)
        self.previous_orderbooks = {}
        logger.info("✅ Signal Generator v3.0 (OI + Patterns) loaded")
    
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
        logger.info(f"🔍 {symbol}: Начинаю анализ для SHORT (памп: +{pump_data['increase_pct']:.2f}%)")
        
        # 🔥 СТРОГИЕ ФИЛЬТРЫ ДЛЯ ЛУЧШИХ ШОРТОВ
        pump_type = pump_data.get('pump_type', '')
        is_fast_pump = pump_type in ['MASSIVE', 'FAST_IMPULSE', 'MICRO_PUMP']  # Включаем ножи!
        
        # Адаптивные параметры для быстрых пампов
        MIN_RSI_FOR_SHORT = 55 if is_fast_pump else 65  # Меньше RSI для быстрых
        MIN_DEX_SPREAD_PCT = 5.0
        MAX_DISTANCE_FROM_PEAK_PCT = 15 if is_fast_pump else 10  # Больше диапазон для быстрых
        
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
        if is_fast_pump:
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
        
        # 📊 OPEN INTEREST анализ
        # При ПАМПЕ: Рост OI = шорты ликвидируются = пик близко = ХОРОШО для входа в шорт!
        # Падение OI = лонги закрываются = тоже хорошо
        oi_result = await self.oi_analyzer.analyze(symbol)
        oi_score = oi_result.get('oi_score', 5.0)
        oi_change = oi_result.get('oi_change', {})
        oi_change_pct = oi_change.get('oi_change_pct', 0) if oi_change else 0
        
        # 🔥 НОВАЯ ЛОГИКА: при памповых движениях РОСТ OI — это ликвидации шортистов!
        if oi_change_pct > 10:  # OI сильно растёт при пампе
            # Шорты ликвидируются — пик близко!
            oi_bonus = min(2.0, oi_change_pct / 10)
            bonus_score += oi_bonus
            logger.warning(f"🔥 {symbol}: OI РОСТ +{oi_change_pct:.1f}% = ЛИКВИДАЦИИ ШОРТОВ! Бонус +{oi_bonus:.1f}")
        elif oi_score > 6:  # OI падает - лонги закрываются
            oi_bonus = (oi_score - 5) / 5 * 1.5  # До +1.5
            bonus_score += oi_bonus
            logger.info(f"📉 {symbol}: OI падает (лонги закрываются) бонус +{oi_bonus:.1f}")
        
        # 📜 ИСТОРИЧЕСКИЙ ПАТТЕРН монеты
        pattern_result = self.pattern_analyzer.analyze(symbol)
        pattern_score = pattern_result.get('pattern_score', 5.0)
        pattern_type = pattern_result.get('pattern', 'UNKNOWN')
        
        if pattern_type == 'V_SHAPE':
            # Монета обычно восстанавливается - НЕ ШОРТИТЬ!
            bonus_score -= 3.0
            logger.warning(f"⚠️ {symbol}: V-SHAPE монета - пенальти -3.0!")
        elif pattern_type == 'SLOW_BLEED':
            bonus_score += 1.5
            logger.info(f"✅ {symbol}: SLOW_BLEED - бонус +1.5")
        elif pattern_type == 'L_SHAPE':
            bonus_score += 1.0
            logger.info(f"✅ {symbol}: L_SHAPE - бонус +1.0")
        
        # 🔥 DEX СПРЕД - МОЩНЫЙ БОНУС
        if dex_score > 0:
            if pump_type in ['MASSIVE', 'FAST_IMPULSE']:
                dex_bonus = (dex_score / 10) * 4.0
                logger.warning(f"💎💎 {symbol}: DEX бонус +{dex_bonus:.1f} (приоритетный)!")
            else:
                dex_bonus = (dex_score / 10) * 2.0
                logger.warning(f"💎 {symbol}: DEX бонус +{dex_bonus:.1f}!")
            bonus_score += dex_bonus
        
        quality_score = base_score + bonus_score
        display_score = min(quality_score, 10.0)
        
        logger.info(f"📊 {symbol}: Quality Score = {quality_score:.2f} (база: {base_score:.2f} + бонус: {bonus_score:.2f})")
        logger.info(f"   Факторы: div={divergence_score:.1f}, vol={volume_score:.1f}, ob={orderbook_score:.1f}, rsi={rsi:.0f}")
        logger.info(f"   Веса: div={weights['divergence']:.2f}, vol={weights['volume_drop']:.2f}, ob={weights['orderbook']:.2f}, rsi={weights['rsi_level']:.2f}")
        
        # 🎯 СИСТЕМА A/B/C СИГНАЛОВ (все проходят, но с разным уровнем)
        # A-SIGNAL: 7+ (лучшие)
        # B-SIGNAL: 4.5-7 (хорошие)
        # C-SIGNAL: 2.5-4.5 (рискованные)
        
        MIN_SCORE_FOR_SIGNAL = 2.5  # Минимум для любого сигнала
        
        if quality_score < MIN_SCORE_FOR_SIGNAL:
            logger.warning(f"❌ {symbol}: Качество {quality_score:.2f} < {MIN_SCORE_FOR_SIGNAL} (слишком низкое)")
            return None
        
        # Определяем уровень сигнала
        if quality_score >= 7.0:
            signal_grade = 'A'
            grade_emoji = '🔥'
            grade_text = 'ЛУЧШИЙ ВХОД'
        elif quality_score >= 4.5:
            signal_grade = 'B'
            grade_emoji = '⚡'
            grade_text = 'ХОРОШИЙ ВХОД'
        else:
            signal_grade = 'C'
            grade_emoji = '🎲'
            grade_text = 'РИСКОВАННЫЙ'
        
        logger.warning(f"{grade_emoji} {symbol}: {signal_grade}-SIGNAL ({grade_text}) - Score: {quality_score:.1f}")
        
        # RSI теперь только информация, не блокирует
        if rsi < MIN_RSI_FOR_SHORT:
            logger.info(f"ℹ️ {symbol}: RSI {rsi:.0f} < {MIN_RSI_FOR_SHORT} (низкий, но пропускаем)")
        
        # 2) DEX спред - только информация (данные часто неточны)\r\n        # if dex_spread_data and dex_spread_data.get('spread_pct', 0) < MIN_DEX_SPREAD_PCT:\r\n        #     logger.warning(f\"❌ {symbol}: DEX спред...\")\r\n        #     return None
        
        # 3) Цена должна начать откат от пика (подтверждение разворота)
        peak_price = pump_data.get('price_peak', current_price)
        distance_from_peak = ((peak_price - current_price) / peak_price) * 100
        
        if distance_from_peak > MAX_DISTANCE_FROM_PEAK_PCT:
            logger.warning(f"❌ {symbol}: Цена уже упала на {distance_from_peak:.1f}% от пика (поздно входить)")
            return None
        elif distance_from_peak < 0.5 and not is_fast_pump:
            # Для обычных пампов ждём откат, для быстрых - нет!
            logger.info(f"⏳ {symbol}: Цена ещё на пике, ждём откат...")
            return None
        else:
            logger.info(f"✅ {symbol}: Откат {distance_from_peak:.1f}% от пика - хорошая ТВХ!")
        
        # 9. Определяем точку входа - МАКСИМАЛЬНО БЛИЗКО К ПИКУ!
        if is_fast_pump:
            # Для быстрых пампов: ТВХ = пик - 1% (лимитка близко к пику)
            entry_price = peak_price * 0.99
            logger.warning(f"💥 {symbol}: FAST PUMP - ТВХ на пике-1% @ {entry_price:.8f}")
        elif resistance_price and resistance_price > current_price:
            entry_price = resistance_price
        else:
            # Для обычных: текущая цена или чуть выше
            entry_price = max(current_price, peak_price * 0.95)
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
            "signal_grade": signal_grade,  # A / B / C
            "grade_emoji": grade_emoji,
            "grade_text": grade_text,
            "factors": {
                "divergence_score": divergence_score,
                "volume_drop_pct": volume_drop['volume_drop_pct'],
                "orderbook_score": orderbook_score,
                "rsi_value": rsi,
                "funding_score": funding_score,
                "mtf_score": mtf_score,
                "whale_score": whale_data.get('whale_score', 0) if whale_data else 0,
                "dex_score": dex_score,
                "dex_spread_pct": dex_spread_data.get('spread_pct', 0) if dex_spread_data else 0
            },
            "weights": weights,
            "pump_increase_pct": pump_data['increase_pct'],
            "current_price": current_price,
            "orderbook_analysis": orderbook_analysis,
            "funding_data": funding_data,
            "mtf_data": mtf_data,
            "whale_data": whale_data,
            "dex_data": dex_data,
            "dex_spread": dex_spread_data
        }
        
        logger.warning(f"🎯✅ SHORT СИГНАЛ СГЕНЕРИРОВАН: {symbol} @ {entry_price:.8f}")
        logger.warning(f"   Качество: {display_score:.1f}/10 (база: {base_score:.2f} + бонус: {bonus_score:.2f})")
        logger.warning(f"   Надёжность: {reliability:.1f}/10")
        
        return signal
    
    def format_signal_message(self, signal: Dict) -> str:
        """Форматировать сигнал для Telegram (PREMIUM DESIGN + GRADE)"""
        symbol = signal['symbol']
        entry_price = signal['entry_price']
        quality = signal['quality_score']
        
        # Grade (A/B/C)
        grade = signal.get('signal_grade', 'B')
        grade_text = "PREMIUM" if grade == 'A' else "STANDARD" if grade == 'B' else "RISKY"
        
        # SL/TP
        stop_loss = signal.get('stop_loss', entry_price * 1.05)
        take_profits = signal.get('take_profits', [entry_price * 0.95, entry_price * 0.9, entry_price * 0.85])
        
        msg = f"""
📉 *SHORT*   |   {grade}-TIER

`{symbol}`
Вход: `{entry_price:.8f}`

▸ Памп: +{signal.get('pump_increase_pct', 0):.1f}%
▸ Качество: {quality:.0f}/10 {self._get_stars(quality)}

━━━━━━━━━━━━━━━

🛑 SL: `{stop_loss:.8f}` _(+{((stop_loss - entry_price)/entry_price*100):.1f}%)_

✅ TP1: `{take_profits[0]:.8f}` _({((take_profits[0] - entry_price)/entry_price*100):.1f}%)_
✅ TP2: `{take_profits[1]:.8f}` _({((take_profits[1] - entry_price)/entry_price*100):.1f}%)_
✅ TP3: `{take_profits[2]:.8f}` _({((take_profits[2] - entry_price)/entry_price*100):.1f}%)_
"""
        return msg
    
    def _get_stars(self, score: float) -> str:
        if score >= 8: return "⭐⭐⭐ ИДЕАЛЬНЫЙ"
        if score >= 6: return "⭐⭐ ХОРОШИЙ"
        return "⭐ НОРМАЛЬНЫЙ"
        
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
