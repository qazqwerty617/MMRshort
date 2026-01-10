"""
TURBO версия: REST-based Pump Detector
Сканирует MEXC каждые 1.5 секунды через REST API с persistent session
"""

import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List
from collections import defaultdict
import yaml

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from database import Database
from signal_generator import SignalGenerator
from coin_profiler import CoinProfiler
from mexc_scraper import ListingDetector
from signal_tracker import SignalTracker
from logger import setup_logging, get_logger
from sl_tp_calculator import SmartCalculator
from ultra_orderbook import UltraOrderbook, get_ultra_orderbook
from open_interest_analyzer import OpenInterestAnalyzer
from funding_rate_analyzer import FundingRateAnalyzer
from liquidation_heatmap import LiquidationHeatmap, get_liq_heatmap
from god_brain import GodBrain, get_god_brain
from ml_predictor import MLPredictor, get_ml_predictor
from trailing_tp import TrailingTPTracker, get_trailing_tracker
from advanced_analyzers import (
    MultiTimeframeAnalyzer, get_mtf_analyzer,
    VolumeProfileAnalyzer, get_volume_analyzer,
    CrossPairAnalyzer, get_cross_pair_analyzer
)

logger = setup_logging()


class RestPumpDetector:
    """REST-based детектор пампов (TURBO mode)"""
    
    def __init__(self, config_path: str = "config.yaml"):
        # Загрузка конфигурации
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        # Компоненты
        self.db = Database(self.config['database']['path'])
        self.coin_profiler = CoinProfiler(self.db, self.config['learning'])
        self.signal_generator = SignalGenerator(self.config, self.coin_profiler)
        self.smart_calculator = SmartCalculator(database=self.db)
        self.ultra_ob = get_ultra_orderbook()  # 🔥 Ultra Orderbook Analyzer
        self.oi_analyzer = OpenInterestAnalyzer()  # 🔥 Open Interest Analyzer
        self.funding_analyzer = None  # Will init after session ready
        self.liq_heatmap = get_liq_heatmap()  # 🔥 Liquidation Heatmap
        self.god_brain = get_god_brain()  # 🧠 GOD BRAIN - Learning System
        self.ml_predictor = get_ml_predictor()  # 🤖 ML Predictor
        self.trailing_tracker = get_trailing_tracker()  # 📈 Trailing TP
        self.mtf_analyzer = get_mtf_analyzer()  # ⏱️ Multi-Timeframe
        self.volume_analyzer = get_volume_analyzer()  # 📊 Volume Profile
        self.cross_pair_analyzer = get_cross_pair_analyzer()  # 🔗 Cross-Pair
        
        # Telegram
        self.telegram_token = self.config['telegram']['bot_token']
        self.chat_id = self.config['telegram']['chat_id']
        self.topic_id = self.config['telegram'].get('topic_id')  # ID темы в группе
        self.app = None
        
        # REST API
        self.rest_url = self.config['mexc']['rest_endpoint']
        
        # Persistent HTTP session
        self.session: aiohttp.ClientSession = None
        self.connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=50,
            keepalive_timeout=30
        )
        
        # Хранилище данных
        self.price_snapshots = defaultdict(list)
        self.last_prices = {}
        
        # Статистика
        self.pump_count = 0
        self.signal_count = 0
        self.scan_count = 0
        
        # Cooldown
        self.pump_cooldown = {}
        self.signal_cooldown = {}
        self.active_analyses = set()  # Множество активных задач анализа (чтобы не запускать дубли)
        self.last_notified_peak = {}  # symbol -> last peak price we notified about
        self.last_notified_type = {}  # symbol -> last pump type (MICRO/FAST/MASSIVE)
        self.logged_pumps = {}  # symbol -> timestamp of last log (to prevent spam)
        self.cooldown_minutes = 0  # 🚀 INSTANT: Без cooldown - мгновенные уведомления!
        self.repeat_pump_threshold = self.config['pump_detection'].get('repeat_signal_threshold', 10.0)  # 📢 Повторный сигнал при +10% от пика
        self.no_signal_cooldown = {}  # Cooldown для уведомлений "ТВХ не найдена"
        
        # 🚀 ПАРАМЕТРЫ ДЕТЕКЦИИ ПАМПОВ
        # FAST PUMP: 10%+ за ≤5 минут (ювелирные быстрые пампы)
        self.fast_pump_pct = self.config['pump_detection']['fast_pump']['min_increase_pct']
        self.fast_pump_timeframe = self.config['pump_detection']['fast_pump']['max_timeframe_minutes']
        
        # ELITE PUMP: 20%+ за ≤20 минут (сильные пампы)
        self.elite_pump_pct = self.config['pump_detection']['elite_pump']['min_increase_pct']
        self.elite_pump_timeframe = self.config['pump_detection']['elite_pump']['max_timeframe_minutes']
        
        self.scan_interval = 0.05  # 🚀 TURBO MAX++: 0.05 сек (20 сканов/сек!)
        
        
        # Детектор новых листингов
        self.listing_detector = ListingDetector(on_new_listing=self._on_new_listing)
        
        # Трекер сигналов (Win/Loss)
        self.signal_tracker = SignalTracker()
        
        # Связываем результаты с обучением паттернов
        if hasattr(self.signal_generator, 'pattern_analyzer'):
            self.signal_tracker.on_result_callback = self.signal_generator.pattern_analyzer.record_signal_result
        
        # Callback для отправки результата в Telegram
        self.signal_tracker.on_notification_callback = self._on_signal_result
        
        # 🤖 AUTO-TRAIN ML на старте если есть данные в GOD BRAIN
        try:
            trained = self.ml_predictor.train()
            if trained:
                status = self.ml_predictor.get_status()
                logger.info(f"🤖 ML Model обучена на {status['training_samples']} сигналах")
        except Exception as ml_train_err:
            logger.debug(f"ML training on startup skipped: {ml_train_err}")
        
        logger.info("🔄 REST Detector + Listing + Signal Tracker + ML инициализирован")
    
    async def start_session(self):
        """Инициализировать persistent HTTP сессию"""
        if not self.session:
            self.session = aiohttp.ClientSession(connector=self.connector)
            logger.info("🌐 HTTP сессия создана")
    
    async def _on_new_listing(self, symbol: str, contract_data: dict):
        """Callback при обнаружении нового листинга"""
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            
            base_coin = contract_data.get('baseCoin', symbol.replace('_USDT', ''))
            max_lev = contract_data.get('maxLeverage', 0)
            
            msg = f"""
🚀🚀🚀 **НОВЫЙ ЛИСТИНГ ФЬЮЧЕРСА!**

**Пара:** `{symbol}`
**Монета:** {base_coin}
**Плечо:** до x{max_lev}

⚡ Только что добавлен на MEXC Futures!
"""
            
            mexc_url = f"https://futures.mexc.com/exchange/{symbol}?type=linear_swap"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Открыть на MEXC", url=mexc_url)]
            ])
            
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=msg,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"Ошибка уведомления о листинге: {e}")

    async def _on_signal_result(self, signal_data: dict):
        """Callback: результат отработки сигнала"""
        try:
            symbol = signal_data['symbol']
            result = signal_data.get('result')  # 'win' / 'loss'
            profit = signal_data.get('profit_pct', 0)
            entry = signal_data['entry_price']
            
            if result == 'win':
                msg = f"✅ **WIN {symbol}**\n\nВход: `{entry:.8f}`\nПрофит: **+{profit:.2f}%** 🤑"
            else:
                msg = f"❌ **LOSS {symbol}**\n\nВход: `{entry:.8f}`\nУбыток: {profit:.2f}%"
                
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=msg,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка отправки результата: {e}")
    
    async def close_session(self):
        """Закрыть HTTP сессию"""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("🔌 HTTP сессия закрыта")
    
    async def get_all_symbols(self) -> List[str]:
        """Получить все фьючерсные пары"""
        try:
            url = f"{self.rest_url}/api/v1/contract/detail"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("success"):
                        symbols = [item["symbol"] for item in data.get("data", [])]
                        return symbols
        except Exception as e:
            logger.error(f"Ошибка получения списка пар: {e}")
        return []
    
    async def get_ticker_batch(self, session: aiohttp.ClientSession) -> Dict:
        """Получить все тикеры одним запросом"""
        try:
            url = f"{self.rest_url}/api/v1/contract/ticker"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("success"):
                        tickers = {}
                        for ticker in data.get("data", []):
                            symbol = ticker.get("symbol")
                            if symbol:
                                tickers[symbol] = {
                                    "last": float(ticker.get("lastPrice", 0)),
                                    "volume": float(ticker.get("volume24", 0)),
                                    "timestamp": int(datetime.now().timestamp() * 1000)
                                }
                        return tickers
        except Exception as e:
            logger.error(f"Ошибка получения тикеров: {e}")
        return {}
    
    def detect_pump(self, symbol: str) -> bool:
        """
        🚀 ULTRA PUMP DETECTOR v2.0
        Обнаруживает пампы двух уровней:
        - FAST: 10%+ за ≤5 минут (ювелирные быстрые пампы)
        - ELITE: 20%+ за ≤20 минут (сильные пампы)
        """
        if symbol not in self.price_snapshots:
            return False, 0, 0, ""
        
        snapshots = self.price_snapshots[symbol]
        if len(snapshots) < 2:
            return False, 0, 0, ""
        
        now = datetime.now()
        current_price = snapshots[-1][1]
        
        # 🔥 ПРОВЕРЯЕМ ОБА ОКНА ВРЕМЕНИ
        is_pump = False
        pump_type = ""
        best_increase = 0
        best_time = 0
        
        # === ПРОВЕРКА 1: FAST PUMP (10%+ за ≤5 мин) ===
        cutoff_fast = now - timedelta(minutes=self.fast_pump_timeframe)
        recent_fast = [s for s in snapshots if datetime.fromtimestamp(s[0]/1000) >= cutoff_fast]
        
        if len(recent_fast) >= 2:
            min_snap_fast = min(recent_fast, key=lambda x: x[1])
            max_snap_fast = max(recent_fast, key=lambda x: x[1])
            
            price_start_fast = min_snap_fast[1]
            price_peak_fast = max_snap_fast[1]
            
            if price_start_fast > 0:
                increase_fast = ((price_peak_fast - price_start_fast) / price_start_fast) * 100
                time_fast = (max_snap_fast[0] - min_snap_fast[0]) / 1000 / 60
                
                if time_fast <= 0:
                    time_fast = 0.1
                
                # 🚀 FAST PUMP: 10%+ за ≤5 минут
                if increase_fast >= self.fast_pump_pct and time_fast <= self.fast_pump_timeframe:
                    is_pump = True
                    pump_type = "FAST"
                    best_increase = increase_fast
                    best_time = time_fast
        
        # === ПРОВЕРКА 2: ELITE PUMP (20%+ за ≤20 мин) ===
        cutoff_elite = now - timedelta(minutes=self.elite_pump_timeframe)
        recent_elite = [s for s in snapshots if datetime.fromtimestamp(s[0]/1000) >= cutoff_elite]
        
        if len(recent_elite) >= 2:
            min_snap_elite = min(recent_elite, key=lambda x: x[1])
            max_snap_elite = max(recent_elite, key=lambda x: x[1])
            
            price_start_elite = min_snap_elite[1]
            price_peak_elite = max_snap_elite[1]
            
            if price_start_elite > 0:
                increase_elite = ((price_peak_elite - price_start_elite) / price_start_elite) * 100
                time_elite = (max_snap_elite[0] - min_snap_elite[0]) / 1000 / 60
                
                if time_elite <= 0:
                    time_elite = 0.1
                
                # ⚡ ELITE PUMP: 20%+ за ≤20 минут
                # 🔥 ВАЖНО: Приоритет FAST! Если уже нашли FAST, не перезаписываем
                if increase_elite >= self.elite_pump_pct and not is_pump:
                    is_pump = True
                    pump_type = "ELITE"
                    best_increase = increase_elite
                    best_time = time_elite
        
        # 🔥 УМНАЯ ФИЛЬТРАЦИЯ УСТАРЕВШИХ ПАМПОВ
        if is_pump:
            # Находим время с момента пика
            recent = recent_elite if pump_type == "ELITE" else recent_fast
            peak_snap = max(recent, key=lambda x: x[1])
            peak_time = datetime.fromtimestamp(peak_snap[0]/1000)
            time_since_peak = (now - peak_time).total_seconds() / 60
            peak_price = peak_snap[1]
            
            drop_from_peak = ((peak_price - current_price) / peak_price) * 100
            
            # Пропускаем ТОЛЬКО если: пик был > 3 мин назад И цена НЕ упала (всё ещё на хаях)
            # Если цена уже начала падать — это отличный момент для входа!
            if time_since_peak > 3.0 and drop_from_peak < 1.5:
                return False, 0, 0, ""
            
            emoji = "🚀" if pump_type == "FAST" else "⚡"
            logger.warning(f"{emoji} {pump_type} PUMP: {symbol} +{best_increase:.1f}% за {best_time:.1f}мин")
            return True, best_increase, best_time, pump_type
        
        return False, 0, 0, ""
    
    async def scan_market(self):
        """Сканирование рынка"""
        self.scan_count += 1
        
        logger.debug(f"🔍 Сканирование #{self.scan_count}...")
        
        tickers = await self.get_ticker_batch(self.session)
        
        if not tickers:
            logger.warning("⚠️ Не удалось получить тикеры")
            return
        
        logger.debug(f"✅ Получено {len(tickers)} тикеров")
        
        pumps_found = 0
        for symbol, ticker_data in tickers.items():
            price = ticker_data["last"]
            volume = ticker_data["volume"]
            timestamp = ticker_data["timestamp"]
            
            # 🚀 АДАПТИВНОЕ ХРАНЕНИЕ СНИМКОВ v2.0
            # При быстром росте сохраняем КАЖДЫЙ снимок для точности
            # При стабильности - редкие снимки (экономия памяти)
            if not self.price_snapshots[symbol]:
                # Первый снимок - всегда сохраняем
                self.price_snapshots[symbol].append((timestamp, price, volume))
            elif len(self.price_snapshots[symbol]) == 1:
                # Второй снимок - через 1 сек минимум
                if (timestamp - self.price_snapshots[symbol][0][0]) > 1000:
                    self.price_snapshots[symbol].append((timestamp, price, volume))
            else:
                # 🔥 УМНАЯ ЛОГИКА: проверяем скорость роста
                last_price = self.price_snapshots[symbol][-1][1]
                prev_price = self.price_snapshots[symbol][-2][1] if len(self.price_snapshots[symbol]) >= 2 else last_price
                
                # Скорость роста за последний интервал
                if prev_price > 0:
                    price_change_pct = abs((price - last_price) / last_price) * 100
                else:
                    price_change_pct = 0
                
                # Время с последней зафиксированной точки
                prev_historical_time = self.price_snapshots[symbol][-2][0]
                time_since_last = timestamp - prev_historical_time
                
                # 🚀 БЫСТРЫЙ РОСТ: Сохраняем КАЖДЫЙ снимок (каждые 0.05-1 сек)
                if price_change_pct >= 0.5:  # Рост >= 0.5% за интервал
                    # Всегда добавляем новую точку при быстром движении
                    self.price_snapshots[symbol].append((timestamp, price, volume))
                    
                # ⚡ СРЕДНИЙ РОСТ: Сохраняем каждые 2 секунды
                elif price_change_pct >= 0.2 and time_since_last > 2000:
                    self.price_snapshots[symbol].append((timestamp, price, volume))
                    
                # 📊 СТАБИЛЬНОСТЬ: Сохраняем каждые 5 секунд (как было)
                elif time_since_last > 5000:
                    self.price_snapshots[symbol].append((timestamp, price, volume))
                    
                # 🔄 ОБНОВЛЯЕМ ТЕКУЩУЮ ТОЧКУ (Drifting Head)
                else:
                    self.price_snapshots[symbol][-1] = (timestamp, price, volume)
            
            # Очистка старых снимков (окно 40 минут для обоих типов пампов)
            cutoff_time = timestamp - (40 * 60 * 1000)
            self.price_snapshots[symbol] = [
                s for s in self.price_snapshots[symbol]
                if s[0] > cutoff_time
            ]
            
            pump_result = self.detect_pump(symbol)
            if pump_result[0]:
                now = datetime.now()
                
                should_notify = True
                current_peak = max(s[1] for s in self.price_snapshots[symbol][-50:])
                
                # Проверяем: было ли уже уведомление о пампе этой монеты?
                pump_type = pump_result[3]
                last_type = self.last_notified_type.get(symbol, "")
                
                # 🚀 НОВАЯ TIER СИСТЕМА: FAST > ELITE
                tier_values = {"": 0, "FAST": 2, "ELITE": 1}
                current_tier = tier_values.get(pump_type, 0)
                last_tier = tier_values.get(last_type, 0)

                should_notify = True
                
                if symbol in self.last_notified_peak:
                    last_peak = self.last_notified_peak[symbol]
                    peak_increase = ((current_peak - last_peak) / last_peak) * 100
                    
                    # Логика повторного уведомления:
                    # 1. Если TIER повысился (например, ELITE -> FAST) -> УВЕДОМЛЯЕМ СРАЗУ
                    if current_tier > last_tier:
                         logger.info(f"🆙 {symbol}: Level Up! {last_type} -> {pump_type}")
                         should_notify = True
                    # 2. Если TIER тот же, но цена выросла еще на 10% -> УВЕДОМЛЯЕМ
                    elif peak_increase >= self.repeat_pump_threshold:
                         logger.info(f"📈 {symbol}: Новый пик +{peak_increase:.1f}% от последнего ({last_peak:.6f} -> {current_peak:.6f})")
                         should_notify = True
                    # 3. Иначе молчим
                    else:
                         should_notify = False
                
                # 🚀 FAST PUMPS: БЕЗ COOLDOWN - мгновенные уведомления!
                # ELITE PUMPS: тоже без cooldown (cooldown_minutes = 0)
                if symbol in self.pump_cooldown and should_notify:
                    time_since_last = (now - self.pump_cooldown[symbol]).total_seconds() / 60
                    if time_since_last < self.cooldown_minutes:
                        should_notify = False

                pumps_found += 1
                if should_notify:
                    self.pump_count += 1
                    self.pump_cooldown[symbol] = now
                    self.last_notified_peak[symbol] = current_peak  # Запоминаем пик
                    self.last_notified_type[symbol] = pump_result[3] # Запоминаем тип пампа (Tier)
                
                increase_pct = pump_result[1]
                time_minutes = pump_result[2]
                pump_type = pump_result[3]
                
                snapshots = self.price_snapshots[symbol]
                
                # 🚀 ИСПОЛЬЗУЕМ ПРАВИЛЬНОЕ ОКНО в зависимости от типа пампа
                if pump_type == "FAST":
                    cutoff = now - timedelta(minutes=self.fast_pump_timeframe)
                else:
                    cutoff = now - timedelta(minutes=self.elite_pump_timeframe)
                    
                recent = [s for s in snapshots if datetime.fromtimestamp(s[0]/1000) >= cutoff]
                
                if len(recent) < 2:
                    continue
                
                pump_data = {
                    "symbol": symbol,
                    "price_start": recent[0][1],
                    "price_peak": max(s[1] for s in recent),
                    "current_price": price,
                    "increase_pct": increase_pct,
                    "actual_time_minutes": time_minutes,
                    "pump_type": pump_type,
                    "volume_spike": 1.5,
                    "volume_usd": volume * price,
                    "detected_at": datetime.now(),
                    "timeframe_minutes": self.fast_pump_timeframe if pump_type == "FAST" else self.elite_pump_timeframe
                }
                
                if should_notify:
                    await self.send_pump_alert(pump_data)
                
                # Запускаем анализ В ФОНЕ (только если еще не анализируем ИЛИ новый пик)
                already_analyzing = symbol in self.active_analyses
                new_higher_high = symbol in self.last_notified_peak and current_peak > self.last_notified_peak[symbol] * 1.05
                
                if not already_analyzing or new_higher_high:
                    if new_higher_high:
                        logger.info(f"🆕 {symbol}: Новый хай! Рестартую анализ.")
                    self.active_analyses.add(symbol)
                    asyncio.create_task(self._analyze_with_notification(symbol, pump_data, now))
                else:
                    logger.debug(f"🔄 {symbol}: Анализ уже идёт, пропускаем")
        
        logger.info(f"📊 Скан #{self.scan_count}: {pumps_found} пампов | Всего: {self.pump_count} пампов, {self.signal_count} сигналов")
    
    async def _analyze_with_notification(self, symbol: str, pump_data: Dict, detected_time: datetime):
        """
        🚀 ULTRA FAST ANALYSIS v2.0
        Мониторинг монеты после пампа с адаптивными параметрами:
        - FAST пампы: короткий таймаут, низкий порог разворота
        - ELITE пампы: стандартный мониторинг
        """
        try:
            start_price = pump_data.get('price_start')
            peak_price = pump_data.get('price_peak')
            increase_pct = pump_data.get('increase_pct', 0)
            pump_type = pump_data.get('pump_type', '')
            actual_time = pump_data.get('actual_time_minutes', 20)
            start_time = datetime.now()
            
            # 🚀 АДАПТИВНЫЕ ПАРАМЕТРЫ В ЗАВИСИМОСТИ ОТ ТИПА ПАМПА
            if pump_type == "FAST":
                # FAST: Быстрый таймаут, низкий порог разворота
                confirmation_timeout = 60   # Ждём всего 1 минуту
                reversal_threshold = 0.5    # Порог разворота 0.5%
                check_interval = 0.5        # Проверка каждые 0.5 сек
                emoji = "🚀"
            else:
                # ELITE: Стандартные параметры
                confirmation_timeout = 120  # 2 минуты
                reversal_threshold = 1.0    # Порог разворота 1%
                check_interval = 1.0        # Проверка каждую секунду
                emoji = "⚡"
            
            logger.warning(f"{emoji} {symbol}: {pump_type} PUMP +{increase_pct:.1f}% за {actual_time:.1f}мин - жду разворот...")
            
            confirmation_start = datetime.now()
            confirmed = False
            current_price = peak_price
            
            while (datetime.now() - confirmation_start).total_seconds() < confirmation_timeout:
                await asyncio.sleep(check_interval)
                
                if symbol in self.price_snapshots and self.price_snapshots[symbol]:
                    current_price = self.price_snapshots[symbol][-1][1]
                    
                    # Обновляем пик если цена выросла ещё
                    if current_price > peak_price:
                        peak_price = current_price
                        pump_data['price_peak'] = peak_price
                        continue
                    
                    # Проверяем откат от пика
                    drop_from_peak = ((peak_price - current_price) / peak_price) * 100
                    
                    if drop_from_peak >= reversal_threshold:
                        logger.warning(f"✅ {symbol}: РАЗВОРОТ! Откат -{drop_from_peak:.1f}% от пика")
                        confirmed = True
                        break
                    elif drop_from_peak >= reversal_threshold * 0.5:
                        logger.info(f"⏳ {symbol}: Начало отката -{drop_from_peak:.2f}%, жду {reversal_threshold}%+...")
            
            if confirmed:
                # ТВХ = текущая цена (уже откатилась от пика)
                instant_entry = current_price
                pump_data['current_price'] = current_price
                await self.send_instant_short_signal(symbol, pump_data, instant_entry)
                self.signal_cooldown[symbol] = datetime.now()
                return
            
            # Если разворот не подтвердился - короткий мониторинг
            logger.info(f"🔄 {symbol}: Разворот не подтверждён, продолжаю краткий мониторинг...")
            
            max_duration = 15 * 60  # 15 минут (было 45)
            
            while (datetime.now() - start_time).total_seconds() < max_duration:
                elapsed = (datetime.now() - start_time).total_seconds()
                
                # Адаптивный интервал: 2 сек первые 2 мин, потом 5 сек
                monitor_interval = 2 if elapsed < 120 else 5
                
                # 1. Обновляем текущую цену
                current_price = 0
                if symbol in self.price_snapshots and self.price_snapshots[symbol]:
                     current_price = self.price_snapshots[symbol][-1][1]
                     pump_data['current_price'] = current_price
                
                if current_price == 0:
                    await asyncio.sleep(monitor_interval)
                    continue

                # 2. Пробуем найти сигнал
                signal = await self.analyze_and_generate_signal(symbol, pump_data)
                
                if signal:
                    logger.info(f"✅ {symbol}: ТВХ найдена! Завершаю мониторинг.")
                    self.signal_cooldown[symbol] = datetime.now()
                    return
                
                # 3. Проверяем, не упала ли монета (Pump Dumped)
                movement = peak_price - start_price
                retrace_threshold = peak_price - (movement * 0.7)
                
                if current_price < retrace_threshold or current_price <= start_price * 1.01:
                    logger.warning(f"📉 {symbol}: Монета упала без сигнала.")
                    await self.send_no_signal_notification(symbol, pump_data, reason="Цена упала, ТВХ не найдена")
                    return

                await asyncio.sleep(monitor_interval)
            
            logger.info(f"⌛ {symbol}: Таймаут мониторинга (15 мин).")
            
        except Exception as e:
            logger.error(f"❌ {symbol}: Ошибка мониторинга: {e}")
        finally:
            self.active_analyses.discard(symbol)
    
    async def send_no_signal_notification(self, symbol: str, pump_data: Dict, reason: str = "Не прошли фильтры"):
        """Уведомление что ТВХ не найдена и мониторинг завершён (макс 1 раз в 30 мин на символ)"""
        try:
            # Проверяем cooldown чтобы не спамить
            now = datetime.now()
            if symbol in self.no_signal_cooldown:
                time_since_last = (now - self.no_signal_cooldown[symbol]).total_seconds() / 60
                if time_since_last < 30:  # Молчим 30 минут после последнего уведомления
                    logger.debug(f"🔇 {symbol}: Пропуск уведомления (cooldown {30 - time_since_last:.1f} мин)")
                    return
            
            # Запоминаем время уведомления
            self.no_signal_cooldown[symbol] = now
            
            msg = f"""
❌ *Вход не найден*

`{symbol}` — +{pump_data['increase_pct']:.1f}%
"""
            await self.broadcast_message(
                text=msg,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки no-signal: {e}")
    
    async def send_instant_short_signal(self, symbol: str, pump_data: Dict, entry_price: float):
        """
        🔥 INSTANT SHORT - мгновенный сигнал для экстремальных пампов
        Отправляется сразу на пике без ожидания
        """
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            
            increase_pct = pump_data.get('increase_pct', 0)
            peak_price = pump_data.get('price_peak', entry_price)
            
            self.signal_count += 1
            logger.warning(f"⚡🎯 INSTANT SHORT #{self.signal_count}: {symbol} @ {entry_price:.8f}")
            
            # === SMART SL/TP CALCULATION ===
            
            start_price = pump_data.get('price_start', entry_price * 0.8)
            actual_time = pump_data.get('actual_time_minutes', 5.0)
            
            # 🔥 BTC CORRELATION CHECK
            btc_score = 5.0
            btc_emoji = "➡️"
            try:
                async with self.session.get(f"{self.rest_url}/api/v1/contract/ticker?symbol=BTC_USDT") as resp:
                    if resp.status == 200:
                        btc_data = await resp.json()
                        if btc_data.get('success'):
                            ticker = btc_data.get('data', {})
                            btc_change = float(ticker.get('riseFallRate', 0)) * 100  # % change 24h
                            if btc_change <= -3:
                                btc_score = 9.0  # BTC dumping hard = GREAT for short
                                btc_emoji = "📉"
                            elif btc_change <= -1:
                                btc_score = 7.0  # BTC falling = good for short
                                btc_emoji = "📉"
                            elif btc_change >= 3:
                                btc_score = 2.0  # BTC pumping = risky for short
                                btc_emoji = "📈"
                            elif btc_change >= 1:
                                btc_score = 4.0  # BTC rising = less ideal
                                btc_emoji = "📈"
            except Exception as btc_err:
                logger.debug(f"BTC check error: {btc_err}")
            
            # 🔥 FETCH FRESH ORDERBOOK
            orderbook = None
            ob_analysis = None
            try:
                ob_url = f"{self.rest_url}/api/v1/contract/depth/{symbol}"
                async with self.session.get(ob_url, params={"limit": 50}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('success'):
                            ob_data = data.get('data', {})
                            orderbook = {
                                "asks": ob_data.get('asks', []),
                                "bids": ob_data.get('bids', [])
                            }
                            # 🔥 ULTRA ORDERBOOK ANALYSIS
                            ob_analysis = self.ultra_ob.analyze(orderbook, entry_price)
                            if ob_analysis.get("short_score", 5) >= 6:
                                logger.info(f"📊 {symbol}: Ultra OB Score {ob_analysis['short_score']:.1f}/10 | {ob_analysis.get('summary', '')}")
            except Exception as ob_err:
                logger.debug(f"Ошибка получения стакана: {ob_err}")
            
            # Получаем свечи для анализа формы и ATR
            klines = []
            try:
                klines_url = f"{self.rest_url}/api/v1/contract/kline/{symbol}"
                async with self.session.get(klines_url, params={"interval": "Min1", "limit": 30}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('success'):
                            raw_klines = data.get('data', [])
                            for k in raw_klines:
                                if isinstance(k, dict):
                                    klines.append([
                                        k.get('time', 0),
                                        float(k.get('open', 0)),
                                        float(k.get('high', 0)),
                                        float(k.get('low', 0)),
                                        float(k.get('close', 0)),
                                        float(k.get('vol', 0))
                                    ])
            except Exception as ke:
                logger.debug(f"Не удалось получить свечи для Smart TP: {ke}")

            smart_levels = self.smart_calculator.calculate(
                symbol=symbol,
                entry_price=entry_price,
                peak_price=peak_price,
                start_price=start_price,
                pump_speed_minutes=actual_time,
                klines=klines,
                orderbook=orderbook
            )
            
            # 🔥 OVERRIDE TPs FROM ORDERBOOK IF AVAILABLE
            if ob_analysis and ob_analysis.get("tp_targets"):
                ob_tps = self.ultra_ob.get_optimal_tps_from_orderbook(ob_analysis, entry_price)
                if ob_tps:
                    # Смешиваем: 50% Фибо + 50% ордербук
                    fib_tps = smart_levels['take_profits']
                    smart_levels['take_profits'] = [
                        (fib_tps[0] + ob_tps[0]) / 2,
                        (fib_tps[1] + ob_tps[1]) / 2,
                        (fib_tps[2] + ob_tps[2]) / 2
                    ]
                    logger.info(f"📊 {symbol}: TP скорректированы по ликвидности стакана")
            
            sl = smart_levels['stop_loss']
            tps = smart_levels['take_profits']
            
            # Формируем красивые строки
            sl_pct_diff = ((sl - entry_price) / entry_price) * 100
            tp1_pct_diff = ((tps[0] - entry_price) / entry_price) * 100
            tp2_pct_diff = ((tps[1] - entry_price) / entry_price) * 100
            tp3_pct_diff = ((tps[2] - entry_price) / entry_price) * 100

            # Получаем GodEye и Dominator данные из анализа
            analysis = smart_levels.get('analysis', {})
            god_eye_score = analysis.get('god_eye_score', 5.0)
            god_eye_quality = analysis.get('god_eye_quality', '⭐ СТАНДАРТ')
            dominator_score = analysis.get('dominator_score', 5.0)
            domination_signal = analysis.get('domination_signal', 'NEUTRAL')
            final_mult = analysis.get('final_multiplier', 1.0)
            
            # 🔥 OPEN INTEREST ANALYSIS
            oi_score = 5.0
            oi_emoji = "➡️"
            try:
                oi_result = await self.oi_analyzer.analyze(symbol, self.session)
                if oi_result.get('oi_change'):
                    oi_score = oi_result.get('oi_score', 5.0)
                    oi_trend = oi_result['oi_change'].get('oi_trend', 'stable')
                    if oi_trend == 'falling':
                        oi_emoji = "🔻"  # OI падает = хорошо
                    elif oi_trend == 'rising':
                        oi_emoji = "🔺"  # OI растёт = осторожно
            except Exception as oi_err:
                logger.debug(f"OI analysis error: {oi_err}")
            
            # 🔥 FUNDING RATE ANALYSIS
            funding_score = 5.0
            funding_emoji = "➡️"
            try:
                async with self.session.get(f"{self.rest_url}/api/v1/contract/funding_rate/{symbol}") as resp:
                    if resp.status == 200:
                        f_data = await resp.json()
                        if f_data.get('success'):
                            fr = float(f_data.get('data', {}).get('fundingRate', 0))
                            fr_pct = fr * 100
                            if fr_pct >= 0.10:
                                funding_score = 9.0
                                funding_emoji = "🔥"
                            elif fr_pct >= 0.05:
                                funding_score = 7.0
                                funding_emoji = "✅"
                            elif fr_pct > 0:
                                funding_score = 5.0
                                funding_emoji = "➡️"
                            else:
                                funding_score = 2.0
                                funding_emoji = "⚠️"
            except Exception as fr_err:
                logger.debug(f"Funding rate error: {fr_err}")
            
            # 🔥 ORDERBOOK SCORE
            ob_score = ob_analysis.get('short_score', 5.0) if ob_analysis else 5.0
            
            # 🔥 LIQUIDATION HEATMAP
            liq_score = 5.0
            liq_analysis = None
            try:
                liq_analysis = self.liq_heatmap.calculate_liquidation_zones(
                    current_price=entry_price,
                    peak_price=peak_price,
                    start_price=start_price
                )
                liq_score = liq_analysis.get('liq_score', 5.0)
                if liq_score >= 7:
                    logger.info(f"🔥 {symbol}: Liquidation Heatmap Score {liq_score:.1f}/10 - {self.liq_heatmap.get_summary(liq_analysis)}")
            except Exception as liq_err:
                logger.debug(f"Liquidation heatmap error: {liq_err}")
            
            # ⏱️ MULTI-TIMEFRAME ANALYSIS
            mtf_score = 5.0
            try:
                mtf_result = await self.mtf_analyzer.analyze(symbol, self.session)
                mtf_score = mtf_result.get('short_score', 5.0)
                if mtf_result.get('confluence') in ['STRONG_SHORT', 'AVOID_SHORT']:
                    logger.info(f"⏱️ {symbol}: {mtf_result.get('summary', '')}")
            except Exception as mtf_err:
                logger.debug(f"MTF analysis error: {mtf_err}")
            
            # 📊 VOLUME PROFILE
            vol_score = 5.0
            try:
                vol_result = await self.volume_analyzer.analyze(symbol, entry_price, self.session)
                vol_score = vol_result.get('score', 5.0)
            except Exception as vol_err:
                logger.debug(f"Volume profile error: {vol_err}")
            
            # � CROSS-PAIR CORRELATION
            cross_score = 5.0
            try:
                cross_result = await self.cross_pair_analyzer.analyze(symbol, self.session)
                cross_score = cross_result.get('score', 5.0)
                if cross_result.get('correlation') in ['SECTOR_PUMP', 'SECTOR_DUMP']:
                    logger.info(f"🔗 {symbol}: {cross_result.get('summary', '')}")
            except Exception as cross_err:
                logger.debug(f"Cross-pair error: {cross_err}")
            
            # �🔥 COMBINED QUALITY SCORE (0-10) - 10 метрик!
            combined_score = (god_eye_score + dominator_score + oi_score + funding_score + 
                             ob_score + btc_score + liq_score + mtf_score + vol_score + cross_score) / 10
            
            # 🧠 GOD BRAIN v2.0: SMART PREDICTION (максимальный интеллект)
            smart_pred = self.god_brain.get_smart_prediction(symbol, increase_pct, combined_score)
            adjusted_score = smart_pred['final_score']  # Уже скорректированный score
            
            # 🤖 ML PREDICTOR: Машинное обучение для вероятности WIN
            ml_prob = 0.5
            try:
                ml_result = self.ml_predictor.predict({
                    'pump_pct': increase_pct,
                    'combined_score': combined_score,
                    'god_eye_score': god_eye_score,
                    'dominator_score': dominator_score,
                    'orderbook_score': ob_score,
                    'oi_score': oi_score,
                    'funding_score': funding_score,
                    'btc_score': btc_score,
                    'liq_score': liq_score
                })
                ml_prob = ml_result.get('probability', 0.5)
                if ml_result.get('confidence') != 'NO_MODEL':
                    logger.info(f"🤖 {symbol}: ML WIN prob {ml_prob*100:.0f}% | {ml_result.get('recommendation', '')}")
                    # Blend ML с GOD BRAIN (50/50)
                    ml_score = ml_prob * 10  # Конвертируем 0-1 в 0-10
                    adjusted_score = (adjusted_score + ml_score) / 2
            except Exception as ml_err:
                logger.debug(f"ML prediction error: {ml_err}")
            
            # Логируем финальный результат
            if smart_pred['confidence'] >= 50:
                reasoning_str = " | ".join(smart_pred['reasoning'][:2]) if smart_pred['reasoning'] else ""
                logger.info(f"🧠 {symbol}: {smart_pred['prediction']} (conf:{smart_pred['confidence']}%) | Final Score:{adjusted_score:.1f}/10 | {reasoning_str}")
            
            # ⚠️ AVOID WARNING: если история плохая, логируем предупреждение
            if smart_pred['prediction'] == 'AVOID' and smart_pred['confidence'] >= 70:
                logger.warning(f"⚠️ {symbol}: GOD BRAIN рекомендует AVOID но сигнал отправлен (WR слишком низкая)")
            
            # Используем adjusted_score для label
            if adjusted_score >= 8:
                quality_label = "🏆 A-TIER"
            elif adjusted_score >= 6:
                quality_label = "✅ B-TIER"
            else:
                # 🚫 C-TIER — не отправляем сигнал
                logger.info(f"⚠️ {symbol}: C-TIER ({adjusted_score:.1f}/10) — сигнал пропущен")
                return
            
            # 🧠 Корректируем TP по истории монеты
            adjusted_tps = self.god_brain.get_adjusted_tps(symbol, tps, entry_price)
            if adjusted_tps != tps:
                logger.info(f"🧠 {symbol}: TP скорректированы по истории монеты")
                tps = adjusted_tps
            
            # 📊 Сортируем TP по возрастанию профита (для шорта: чем ниже цена - тем больше профит)
            tps = sorted(tps)  # Сортируем по возрастанию цены (TP1 самый близкий, TP3 самый далёкий)
            
            # Пересчитываем % для отсортированных TP
            tp1_pct_diff = ((tps[0] - entry_price) / entry_price) * 100
            tp2_pct_diff = ((tps[1] - entry_price) / entry_price) * 100
            tp3_pct_diff = ((tps[2] - entry_price) / entry_price) * 100

            msg = f"""
📉 *SHORT* | {quality_label}

`{symbol}`
Вход: `{entry_price:.8f}`
Памп: +{increase_pct:.1f}%

▸ Качество: *{adjusted_score:.1f}/10*
"""
            
            mexc_url = f"https://futures.mexc.com/exchange/{symbol}?type=linear_swap"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Открыть MEXC", url=mexc_url)]
            ])
            
            await self.broadcast_message(
                text=msg,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            
            # Сохраняем в БД
            try:
                pump_id = self.db.add_pump(
                    symbol=symbol,
                    price_start=pump_data.get('price_start', 0),
                    price_peak=peak_price,
                    price_increase_pct=increase_pct,
                    volume_spike=pump_data.get('volume_spike', 1.5),
                    timeframe_minutes=pump_data.get('timeframe_minutes', 20)
                )
                self.db.add_signal(
                    pump_id=pump_id,
                    symbol=symbol,
                    entry_price=entry_price,
                    stop_loss=None,
                    take_profits=[],
                    risk_reward=0,
                    quality_score=9.0,  # Высокий score для instant
                    factors={"instant_short": True, "pump_pct": increase_pct},
                    weights={}
                )
                
                # Регистрируем в трекере
                self.signal_tracker.add_signal(
                    symbol=symbol,
                    entry_price=entry_price,
                    peak_price=peak_price,
                    pump_pct=increase_pct
                )
                
                # 🧠 GOD BRAIN: Записываем сигнал для обучения
                self.god_brain.record_signal({
                    'symbol': symbol,
                    'pump_pct': increase_pct,
                    'pump_speed_minutes': pump_data.get('actual_time_minutes', 5.0),
                    'entry_price': entry_price,
                    'peak_price': peak_price,
                    'start_price': pump_data.get('price_start', entry_price * 0.8),
                    'god_eye_score': god_eye_score,
                    'dominator_score': dominator_score,
                    'orderbook_score': ob_score,
                    'oi_score': oi_score,
                    'funding_score': funding_score,
                    'btc_score': btc_score,
                    'liq_score': liq_score,
                    'combined_score': combined_score,
                    'sl_price': sl,
                    'tp1_price': tps[0] if tps else None,
                    'tp2_price': tps[1] if len(tps) > 1 else None,
                    'tp3_price': tps[2] if len(tps) > 2 else None
                })
                
                # 📈 TRAILING TP: Регистрируем позицию для trailing
                signal_id = f"{symbol}_{datetime.now().timestamp()}"
                self.trailing_tracker.add_position(
                    signal_id=signal_id,
                    symbol=symbol,
                    entry_price=entry_price,
                    sl_price=sl,
                    initial_tps=tps
                )
            except Exception as db_err:
                logger.warning(f"⚠️ Ошибка БД (instant): {db_err}")
            
        except Exception as e:
            logger.error(f"Ошибка instant short: {e}")
    
    async def send_pump_alert(self, pump_data: Dict):
        """Отправить уведомление о пампе"""
        try:
            actual_time = pump_data.get('actual_time_minutes', pump_data['timeframe_minutes'])
            msg = f"""
◈ *Pump Detected*

`{pump_data['symbol']}`
+{pump_data['increase_pct']:.1f}% in {actual_time:.1f}m
`{pump_data['price_start']:.8f}` ➔ `{pump_data['price_peak']:.8f}`

_Analyzing..._
"""
            await self.broadcast_message(
                text=msg,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")
    
    async def analyze_and_generate_signal(self, symbol: str, pump_data: Dict):
        """Анализ и генерация сигнала"""
        logger.info(f"🔄 {symbol}: Анализ для SHORT...")
        
        try:
            klines_url = f"{self.rest_url}/api/v1/contract/kline/{symbol}"
            async with self.session.get(klines_url, params={"interval": "Min1", "limit": 100}) as resp:
                klines = []
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        if data.get("success") and isinstance(data.get("data"), list):
                            for k in data.get("data", []):
                                if isinstance(k, dict):
                                    try:
                                        klines.append({
                                            "timestamp": k["time"],
                                            "open": float(k["open"]),
                                            "high": float(k["high"]),
                                            "low": float(k["low"]),
                                            "close": float(k["close"]),
                                            "volume": float(k["vol"])
                                        })
                                    except (KeyError, ValueError, TypeError):
                                        continue
                    except Exception as e:
                        logger.error(f"{symbol}: Ошибка klines: {e}")
            
            ob_url = f"{self.rest_url}/api/v1/contract/depth/{symbol}"
            async with self.session.get(ob_url, params={"limit": 20}) as resp:
                orderbook = None
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        if data.get("success"):
                            orderbook = data.get("data")
                    except Exception as e:
                        logger.error(f"{symbol}: Ошибка orderbook: {e}")
            
            # Fallback: создаем klines из снапшотов
            if not klines:
                if symbol in self.price_snapshots and len(self.price_snapshots[symbol]) >= 5:
                    snapshots = self.price_snapshots[symbol][-100:]
                    minute_data = defaultdict(list)
                    
                    for snap in snapshots:
                        timestamp_ms = snap[0]
                        price = snap[1]
                        volume = snap[2]
                        minute_key = int(timestamp_ms / 60000) * 60000
                        minute_data[minute_key].append((price, volume))
                    
                    for minute_ts in sorted(minute_data.keys()):
                        prices = [p[0] for p in minute_data[minute_ts]]
                        volumes = [p[1] for p in minute_data[minute_ts]]
                        klines.append({
                            "timestamp": minute_ts,
                            "open": prices[0],
                            "high": max(prices),
                            "low": min(prices),
                            "close": prices[-1],
                            "volume": sum(volumes) / len(volumes)
                        })
            
            if not klines:
                return None
            
            snapshots = self.price_snapshots[symbol][-100:]
            price_history = [s[1] for s in snapshots]
            volume_history = [s[2] for s in snapshots]
            
            signal = await self.signal_generator.generate_signal(
                symbol=symbol,
                pump_data=pump_data,
                price_history=price_history,
                volume_history=volume_history,
                klines=klines,
                orderbook=orderbook,
                mexc_client=None
            )
            
            if signal:
                self.signal_count += 1
                logger.info(f"🎯 Сигнал #{self.signal_count} для {symbol}")
                
                msg = self.signal_generator.format_signal_message(signal)
                
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                
                mexc_url = f"https://futures.mexc.com/exchange/{symbol}?type=linear_swap"
                buttons = [[InlineKeyboardButton("📈 MEXC Futures", url=mexc_url)]]
                
                if signal.get('dex_data'):
                    dex_info = signal['dex_data']
                    dex_url = f"https://dexscreener.com/{dex_info['chain']}/{dex_info.get('pair_address', '')}"
                    buttons.append([InlineKeyboardButton("🦄 DexScreener", url=dex_url)])
                
                keyboard = InlineKeyboardMarkup(buttons)

                await self.broadcast_message(
                    text=msg,
                    parse_mode='Markdown',
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
                
                try:
                    pump_id = self.db.add_pump(
                        symbol=pump_data['symbol'],
                        price_start=pump_data['price_start'],
                        price_peak=pump_data['price_peak'],
                        price_increase_pct=pump_data['increase_pct'],
                        volume_spike=pump_data['volume_spike'],
                        timeframe_minutes=pump_data['timeframe_minutes']
                    )
                    self.db.add_signal(
                        pump_id=pump_id,
                        symbol=symbol,
                        entry_price=signal['entry_price'],
                        stop_loss=None,
                        take_profits=[],
                        risk_reward=0,
                        quality_score=signal['quality_score'],
                        factors=signal['factors'],
                        weights=signal['weights']
                    )
                    
                    # Регистрируем в трекере результатов
                    self.signal_tracker.add_signal(
                        symbol=symbol,
                        entry_price=signal['entry_price'],
                        peak_price=pump_data['price_peak'],
                        pump_pct=pump_data['increase_pct']
                    )
                    
                except Exception as db_err:
                    logger.warning(f"⚠️ Ошибка БД: {db_err}")
                
                return signal
            return None
        
        except Exception as e:
            logger.error(f"❌ Ошибка сигнала {symbol}: {e}", exc_info=True)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        await update.message.reply_text(
            "🤖 **REST Pump Detector TURBO**\n\n"
            "Сканирует рынок каждые 1.5 секунды\n"
            "/status - статус\n"
            "/test - тестовый сигнал",
            parse_mode='Markdown'
        )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /status"""
        msg = f"""
📊 **Статус TURBO**

Сканирований: {self.scan_count}
Пампов найдено: {self.pump_count}
Сигналов: {self.signal_count}

Интервал сканирования: {self.scan_interval}с
Мин. рост: {self.min_pump_pct}%
Таймфрейм: {self.timeframe_minutes}мин
"""
        await update.message.reply_text(msg, parse_mode='Markdown')

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /stats - статистика Win/Loss"""
        stats = self.signal_tracker.get_statistics()
        brain_stats = self.god_brain.get_statistics_summary()
        ml_status = self.ml_predictor.get_status()
        trailing_status = self.trailing_tracker.get_status()
        
        # Определяем emoji для WR
        wr = brain_stats.get('win_rate', 0)
        if wr >= 70:
            wr_emoji = "🔥"
        elif wr >= 50:
            wr_emoji = "✅"
        elif wr >= 30:
            wr_emoji = "⚠️"
        else:
            wr_emoji = "❌"
        
        msg = f"""
━━━━━━━━━━━━━━━━━━━━
📊 *СТАТИСТИКА БОТА*
━━━━━━━━━━━━━━━━━━━━

🧠 *GOD BRAIN*
┌─────────────────────
│ 📝 Сигналов: `{brain_stats.get('total', 0)}`
│ ✅ WIN: `{brain_stats.get('wins', 0)}` | ❌ LOSS: `{brain_stats.get('losses', 0)}`
│ {wr_emoji} Win Rate: *{wr:.1f}%*
│ 🪙 Монет изучено: `{brain_stats.get('unique_coins', 0)}`
└─────────────────────

🤖 *ML MODEL*
┌─────────────────────
│ Статус: {'🟢 Обучена' if ml_status.get('is_trained') else '🔴 Ждёт данных'}
│ Сэмплов: `{ml_status.get('training_samples', 0)}/20`
"""
        
        # Progress bar для ML
        ml_progress = min(ml_status.get('training_samples', 0), 20)
        filled = "█" * (ml_progress // 2)
        empty = "░" * (10 - ml_progress // 2)
        msg += f"│ [{filled}{empty}]\n"
        msg += "└─────────────────────\n"
        
        # Top features
        if ml_status.get('top_features'):
            msg += "\n🎯 *ВАЖНЫЕ ФАКТОРЫ*\n"
            for i, (feat, imp) in enumerate(ml_status['top_features'][:3], 1):
                feat_name = feat.replace('_score', '').replace('_', ' ').title()
                bar_len = int(abs(imp) * 20)
                bar = "▓" * min(bar_len, 10)
                msg += f"{i}. {feat_name}: {bar}\n"
        
        # Best coins from GOD BRAIN memory
        if self.god_brain.coin_memory:
            msg += "\n🏆 *TOP МОНЕТЫ*\n"
            sorted_coins = sorted(
                self.god_brain.coin_memory.items(),
                key=lambda x: x[1].get('win_rate', 0) * x[1].get('total_signals', 0),
                reverse=True
            )[:3]
            for sym, data in sorted_coins:
                coin_wr = data.get('win_rate', 0) * 100
                total = data.get('total_signals', 0)
                if total > 0:
                    msg += f"• `{sym}` — {coin_wr:.0f}% WR ({total} сигналов)\n"
        
        # Active tracking
        msg += f"\n⏱️ *АКТИВНЫЕ*\n"
        msg += f"├ Отслеживаний: `{stats['active_tracking']}`\n"
        msg += f"└ Trailing TP: `{trailing_status['active_count']}`\n"
        
        # Uptime indicator
        msg += f"\n━━━━━━━━━━━━━━━━━━━━"
        
        if brain_stats.get('total', 0) == 0:
            msg = """
━━━━━━━━━━━━━━━━━━━━
📊 *СТАТИСТИКА*
━━━━━━━━━━━━━━━━━━━━

📭 *Данных пока нет*

После первых сигналов здесь появится:
• Win Rate по всем монетам
• Лучшие и худшие монеты
• ML модель (после 20 сигналов)
• История по каждой монете

_Бот запущен и готов к работе!_ 🚀
━━━━━━━━━━━━━━━━━━━━
"""
        
        await update.message.reply_text(msg, parse_mode='Markdown')

    async def listing_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /listing - календарь листингов"""
        status_msg = await update.message.reply_text("🔄 Загружаю данные о листингах...")
        
        try:
            msg = ""
            
            # 1. Новые фьючерсы MEXC за 24ч
            mexc_listings = await self.listing_detector.get_recent_listings(hours=24)
            if mexc_listings:
                msg += "📅 **Новые фьючерсы MEXC (24ч)**\n\n"
                for item in mexc_listings[:7]:
                    symbol = item['symbol']
                    time_str = item['time_str']
                    lev = item.get('leverage', 0)
                    mexc_link = f"https://futures.mexc.com/exchange/{symbol}_USDT"
                    msg += f"• [{symbol}]({mexc_link}) — {time_str} (x{lev})\n"
                msg += "\n"
            
            # 2. Анонсы из Telegram канала MEXC
            try:
                from telegram_parser import SimpleTelegramParser
                tg_parser = SimpleTelegramParser()
                tg_listings = await tg_parser.get_listings()
                
                if tg_listings:
                    msg += "📢 **Анонсы из Telegram MEXC**\n\n"
                    for item in tg_listings[:5]:
                        symbols = item.get('symbols', [])
                        listing_type = "🔮 Фьючерс" if item.get('type') == 'futures' else "💰 Спот"
                        trading_time = item.get('trading_time', '')
                        
                        for sym in symbols[:2]:
                            if trading_time:
                                msg += f"{listing_type} **{sym}** — {trading_time}\n"
                            else:
                                msg += f"{listing_type} **{sym}**\n"
                    msg += "\n"
            except Exception as tg_err:
                logger.warning(f"Telegram parser: {tg_err}")
            
            # 3. Binance анонсы (индикатор)
            try:
                from announcement_parser import AnnouncementParser
                parser = AnnouncementParser()
                binance_listings = await parser.get_binance_new_listings()
                
                if binance_listings:
                    msg += "🔮 **Binance анонсы** _(индикатор)_\n\n"
                    shown = 0
                    for item in binance_listings[:5]:
                        for sym in item.get('symbols', [])[:1]:
                            mexc_data = await parser.check_mexc_has_futures(sym)
                            if mexc_data:
                                mexc_link = f"https://futures.mexc.com/exchange/{mexc_data['symbol']}"
                                msg += f"✅ [{sym}]({mexc_link}) — на MEXC\n"
                            else:
                                msg += f"⏳ **{sym}** — ждём\n"
                            shown += 1
                            if shown >= 5:
                                break
                        if shown >= 5:
                            break
            except Exception as bn_err:
                logger.warning(f"Binance parser: {bn_err}")
            
            if not msg:
                msg = "⚠️ Нет данных о листингах\n\n_Совет: следите за каналом @MEXCOfficialNews_"
            
            await status_msg.edit_text(msg, parse_mode='Markdown', disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Ошибка /listing: {e}", exc_info=True)
            await status_msg.edit_text(f"❌ Ошибка: {e}")

    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тестовый сигнал"""
        fake_signal = {
            "symbol": "TEST/USDT",
            "entry_price": 0.045,
            "quality_score": 9.5,
            "raw_quality_score": 9.5,
            "reliability_score": 8.5,
            "pump_increase_pct": 23.5,
            "factors": {
                "divergence_score": 7,
                "volume_drop_pct": 65,
                "orderbook_score": 8,
                "rsi_value": 78,
                "funding_score": 5,
                "mtf_score": 0,
                "whale_score": 8,
                "dex_score": 10,
                "dex_spread_pct": 16.88
            },
            "dex_data": {
                "price": 0.0385,
                "dex_name": "Uniswap",
                "chain": "ethereum",
                "liquidity": 500000
            },
            "whale_data": {"whale_sells_appeared": True}
        }
        
        msg = self.signal_generator.format_signal_message(fake_signal)
        await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)

    async def announce_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Команда /announce - отправить объявление в группу
        """
        # Получаем сообщение
        message = update.effective_message
        if not message:
            return
            
        # Способ 1: Ответ на сообщение (reply)
        if message.reply_to_message:
            announcement_text = message.reply_to_message.text or message.reply_to_message.caption
            if not announcement_text:
                await message.reply_text("⚠️ Ответь на текстовое сообщение!")
                return
        # Способ 2: Текст после команды
        elif message.text and len(message.text) > 10:
            announcement_text = message.text.replace("/announce ", "").replace("/announce", "").strip()
        else:
            await message.reply_text(
                "📢 **Как использовать:**\n\n"
                "**Способ 1:** Ответь на любое сообщение командой /announce\n\n"
                "**Способ 2:** `/announce Текст объявления`\n\n"
                "💡 Для переносов строк используй Enter при вводе!",
                parse_mode='Markdown'
            )
            return
        
        if not announcement_text:
            await update.message.reply_text("⚠️ Пустое сообщение!")
            return
        
        # Форматируем объявление
        msg = f"📢 *ОБЪЯВЛЕНИЕ*\n\n{announcement_text}\n\n_— Админ MMR Bot_"
        
        # Отправляем в группу
        try:
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                message_thread_id=self.topic_id,
                text=msg,
                parse_mode='Markdown'
            )
            await update.message.reply_text("✅ Объявление отправлено в группу!")
        except Exception as e:
            logger.error(f"Ошибка отправки объявления: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def broadcast_message(self, text: str, parse_mode='Markdown', reply_markup=None, disable_web_page_preview=True):
        """Отправить сообщение в группу (в указанную тему)"""
        try:
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                message_thread_id=self.topic_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
        except Exception as e:
            logger.error(f"Ошибка отправки в группу: {e}")
    
    async def send_daily_report(self):
        """Ежедневный отчёт о работе бота"""
        try:
            stats = self.signal_tracker.get_statistics()
            brain_stats = self.god_brain.get_statistics()
            
            total_pumps = self.pump_count
            total_signals = self.signal_count
            wr = brain_stats.get('win_rate', 0) * 100
            
            msg = f"""
📊 **ЕЖЕДНЕВНЫЙ ОТЧЁТ**
━━━━━━━━━━━━━━━

🚀 Пампов обнаружено: `{total_pumps}`
🎯 Сигналов отправлено: `{total_signals}`

📈 **Результаты:**
✅ WIN: `{brain_stats.get('wins', 0)}`
❌ LOSS: `{brain_stats.get('losses', 0)}`
📊 Win Rate: **{wr:.1f}%**

💰 Средний профит: `{stats.get('avg_profit', 0):.1f}%`
🎲 Активных трекингов: `{stats.get('active_tracking', 0)}`
"""
            
            if stats.get('best_coins'):
                msg += "\n🏆 **Топ монеты:**\n"
                for sym, profit, wins, losses in stats['best_coins'][:3]:
                    msg += f"  • {sym}: +{profit:.1f}% ({wins}W/{losses}L)\n"
            
            await self.broadcast_message(msg)
            logger.info("📊 Ежедневный отчёт отправлен")
            
        except Exception as e:
            logger.error(f"Ошибка отправки ежедневного отчёта: {e}")
    
    async def auto_reports_loop(self):
        """Фоновая задача для автоматических отчётов"""
        while True:
            try:
                now = datetime.now()
                # Отправляем отчёт в 23:59
                if now.hour == 23 and now.minute == 59:
                    await self.send_daily_report()
                    await asyncio.sleep(120)  # Спим 2 мин чтобы не дублировать
                else:
                    await asyncio.sleep(60)  # Проверяем каждую минуту
            except Exception as e:
                logger.error(f"Ошибка в auto_reports_loop: {e}")
                await asyncio.sleep(60)

    async def run(self):
        """Запуск бота"""
        await self.start_session()
        
        self.app = Application.builder().token(self.telegram_token).build()
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("listing", self.listing_command))
        self.app.add_handler(CommandHandler("test", self.test_command))
        self.app.add_handler(CommandHandler("announce", self.announce_command))
        
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        
        logger.info("✅ Telegram бот запущен (TURBO: 1.5s)")
        
        # Убрали спам при перезапуске
        # await self.broadcast_message(
        #     text="🟢 **MMR TURBO запущен!**\n\n• Памп детекция: 1.5с\n• Листинг детекция: 30с\n• /stats - статистика",
        #     parse_mode='Markdown'
        # )
        
        # Запускаем детектор листингов в фоне
        listing_task = asyncio.create_task(self.listing_detector.run())
        
        # Запускаем трекер сигналов в фоне
        tracker_task = asyncio.create_task(self.signal_tracker.run())
        
        # 📊 Запускаем автоматические отчёты
        reports_task = asyncio.create_task(self.auto_reports_loop())
        
        try:
            while True:
                await self.scan_market()
                await asyncio.sleep(self.scan_interval)
        
        except KeyboardInterrupt:
            logger.info("Остановка...")
        finally:
            await self.close_session()
            if self.app:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()


async def main():
    bot = RestPumpDetector()
    await bot.run()


if __name__ == "__main__":
    import os
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    asyncio.run(main())
