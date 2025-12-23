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
        
        # Telegram
        self.telegram_token = self.config['telegram']['bot_token']
        self.chat_id = self.config['telegram']['chat_id']
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
        self.cooldown_minutes = 2
        self.repeat_pump_threshold = 10.0  # Повторное уведомление только при +10% от последнего пика
        
        # Параметры детекции
        self.min_pump_pct = self.config['pump_detection']['min_price_increase_pct']
        self.timeframe_minutes = self.config['pump_detection']['timeframe_minutes']
        self.scan_interval = 1.5
        
        
        # Детектор новых листингов
        self.listing_detector = ListingDetector(on_new_listing=self._on_new_listing)
        
        # Трекер сигналов (Win/Loss)
        self.signal_tracker = SignalTracker()
        
        # Связываем результаты с обучением паттернов
        if hasattr(self.signal_generator, 'pattern_analyzer'):
            self.signal_tracker.on_result_callback = self.signal_generator.pattern_analyzer.record_signal_result
        
        # Callback для отправки результата в Telegram
        self.signal_tracker.on_notification_callback = self._on_signal_result
        
        logger.info("🔄 REST Detector + Listing + Signal Tracker инициализирован")
    
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
        """Детектировать памп по накопленным данным"""
        if symbol not in self.price_snapshots:
            return False, 0, 0, ""
        
        snapshots = self.price_snapshots[symbol]
        if len(snapshots) < 2:
            return False, 0, 0, ""
        
        now = datetime.now()
        cutoff = now - timedelta(minutes=self.timeframe_minutes)
        recent = [s for s in snapshots if datetime.fromtimestamp(s[0]/1000) >= cutoff]
        
        if len(recent) < 2:
            return False, 0, 0, ""
        
        price_start = recent[0][1]
        peak_snapshot = max(recent, key=lambda x: x[1])
        price_peak = peak_snapshot[1]
        peak_time = datetime.fromtimestamp(peak_snapshot[0]/1000)
        time_since_peak = (now - peak_time).total_seconds() / 60
        
        if price_start == 0:
            return False, 0, 0, ""
        
        increase_pct = ((price_peak - price_start) / price_start) * 100
        time_diff_seconds = (recent[-1][0] - recent[0][0]) / 1000
        time_diff_minutes = time_diff_seconds / 60
        if time_diff_minutes <= 0:
            time_diff_minutes = 0.1

        is_pump = False
        pump_type = ""

        if time_since_peak > 1.5:
            return False, 0, 0, ""

        if increase_pct >= self.min_pump_pct:
            is_pump = True
            pump_type = "MASSIVE"
        elif increase_pct >= 10.0 and time_diff_minutes <= 5.0:
            is_pump = True
            pump_type = "FAST_IMPULSE"

        if is_pump:
            pump_emoji = "🚀" if pump_type == "MASSIVE" else "⚡️"
            logger.warning(f"{pump_type} {pump_emoji}: {symbol} +{increase_pct:.2f}% за {time_diff_minutes:.1f}мин")
            return True, increase_pct, time_diff_minutes, pump_type

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
            
            self.price_snapshots[symbol].append((timestamp, price, volume))
            
            cutoff_time = timestamp - (self.timeframe_minutes * 2 * 60 * 1000)
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
                if symbol in self.last_notified_peak:
                    last_peak = self.last_notified_peak[symbol]
                    peak_increase = ((current_peak - last_peak) / last_peak) * 100
                    
                    # Уведомляем только если пик вырос на 10%+ от последнего
                    if peak_increase < self.repeat_pump_threshold:
                        should_notify = False
                    else:
                        logger.info(f"📈 {symbol}: Новый пик +{peak_increase:.1f}% от последнего ({last_peak:.6f} -> {current_peak:.6f})")
                
                # Также проверяем cooldown по времени
                if symbol in self.pump_cooldown and should_notify:
                    time_since_last = (now - self.pump_cooldown[symbol]).total_seconds() / 60
                    if time_since_last < self.cooldown_minutes:
                        should_notify = False
                
                if symbol in self.signal_cooldown:
                    time_since_signal = (now - self.signal_cooldown[symbol]).total_seconds() / 60
                    if time_since_signal < 30:
                        continue

                pumps_found += 1
                if should_notify:
                    self.pump_count += 1
                    self.pump_cooldown[symbol] = now
                    self.last_notified_peak[symbol] = current_peak  # Запоминаем пик
                
                increase_pct = pump_result[1]
                time_minutes = pump_result[2]
                pump_type = pump_result[3]
                
                snapshots = self.price_snapshots[symbol]
                cutoff = now - timedelta(minutes=self.timeframe_minutes)
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
                    "timeframe_minutes": self.timeframe_minutes
                }
                
                if should_notify:
                    await self.send_pump_alert(pump_data)
                
                # Запускаем анализ В ФОНЕ (только если еще не анализируем)
                if symbol not in self.active_analyses:
                    self.active_analyses.add(symbol)
                    asyncio.create_task(self._analyze_with_notification(symbol, pump_data, now))
                else:
                    logger.debug(f"🔄 {symbol}: Анализ уже идёт, пропускаем запуск дубля")
        
        logger.info(f"📊 Скан #{self.scan_count}: {pumps_found} пампов | Всего: {self.pump_count} пампов, {self.signal_count} сигналов")
    
    async def _analyze_with_notification(self, symbol: str, pump_data: Dict, detected_time: datetime):
        """
        Мониторинг монеты после пампа (до 45 минут).
        Ищет ТВХ пока цена высокая. 
        Если цена падает без сигнала - сообщает 1 раз.
        """
        try:
            logger.info(f"🔄 {symbol}: Запуск мониторинга ТВХ (макс 45 мин)...")
            
            start_price = pump_data.get('price_start')
            peak_price = pump_data.get('price_peak')
            max_duration = 45 * 60  # 45 минут
            check_interval = 10      # Проверка каждые 10 сек
            start_time = datetime.now()
            
            while (datetime.now() - start_time).total_seconds() < max_duration:
                # 1. Обновляем текущую цену
                current_price = 0
                if symbol in self.price_snapshots and self.price_snapshots[symbol]:
                     current_price = self.price_snapshots[symbol][-1][1]
                     pump_data['current_price'] = current_price
                
                if current_price == 0:
                    await asyncio.sleep(check_interval)
                    continue

                # 2. Пробуем найти сигнал
                signal = await self.analyze_and_generate_signal(symbol, pump_data)
                
                if signal:
                    logger.info(f"✅ {symbol}: ТВХ найдена! Завершаю мониторинг.")
                    self.signal_cooldown[symbol] = datetime.now()
                    return  # Успех! Сигнал отправлен внутри analyze_and_generate_signal
                
                # 3. Проверяем, не упала ли монета (Pump Dumped)
                # Критерий: цена упала ниже (старт + 20% от роста) или просто вернулась к старту
                # Или если прошло > 15 мин и цена < пик - 50% движения
                
                movement = peak_price - start_price
                retrace_threshold = peak_price - (movement * 0.7) # Упала на 70% от движения
                
                # Если цена упала ниже порога отката ИЛИ вернулась к старту (+1%)
                if current_price < retrace_threshold or current_price <= start_price * 1.01:
                    logger.warning(f"📉 {symbol}: Монета упала без сигнала. (Price: {current_price:.6f})")
                    await self.send_no_signal_notification(symbol, pump_data, reason="Цена упала, ТВХ не найдена")
                    return

                # Продолжаем наблюдение
                await asyncio.sleep(check_interval)
            
            logger.info(f"⌛ {symbol}: Таймаут мониторинга (45 мин).")
            
        except Exception as e:
            logger.error(f"❌ {symbol}: Ошибка мониторинга: {e}")
        finally:
            # Обязательно удаляем из активных, чтобы можно было снова пустить анализ если будет новый памп
            self.active_analyses.discard(symbol)
    
    async def send_no_signal_notification(self, symbol: str, pump_data: Dict, reason: str = "Не прошли фильтры"):
        """Уведомление что ТВХ не найдена и мониторинг завершён"""
        try:
            msg = f"""
⚠️ **ТВХ не найдена**

Пара: `{symbol}`
Памп: +{pump_data['increase_pct']:.1f}%

📝 Итог: **Мониторинг завершён**
Причина: {reason}
"""
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=msg,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки no-signal: {e}")
    
    async def send_pump_alert(self, pump_data: Dict):
        """Отправить уведомление о пампе"""
        try:
            actual_time = pump_data.get('actual_time_minutes', pump_data['timeframe_minutes'])
            msg = f"""
🚀 **ПАМП ОБНАРУЖЕН**

Пара: `{pump_data['symbol']}`
Рост: +{pump_data['increase_pct']:.2f}% за {actual_time:.1f} минут
Цена: {pump_data['price_start']:.8f} → {pump_data['price_peak']:.8f}

⏳ Генерирую сигнал...
"""
            await self.app.bot.send_message(
                chat_id=self.chat_id,
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

                await self.app.bot.send_message(
                    chat_id=self.chat_id,
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
        
        # Основная статистика
        msg = f"""
📈 **Статистика сигналов**

**Общий результат:**
Всего сделок: {stats['total']}
✅ Win: {stats['wins']} | ❌ Loss: {stats['losses']}
Винрейт: **{stats['win_rate']:.1f}%**

**Профит:**
Средний профит: {stats['avg_profit']:+.2f}%
Общий профит: {stats['total_profit']:+.2f}%
Средний WIN: +{stats['avg_win']:.2f}%
Средний LOSS: {stats['avg_loss']:.2f}%

🔄 Активных отслеживаний: {stats['active_tracking']}
"""
        
        # Лучшие монеты
        if stats['best_coins']:
            msg += "\n🏆 **Лучшие монеты:**\n"
            for sym, profit, wins, losses in stats['best_coins'][:3]:
                msg += f"• `{sym}` — {profit:+.1f}% ({wins}W/{losses}L)\n"
        
        # Худшие монеты
        if stats['worst_coins'] and stats['total'] > 5:
            msg += "\n💀 **Худшие монеты:**\n"
            for sym, profit, wins, losses in stats['worst_coins'][:2]:
                if profit < 0:
                    msg += f"• `{sym}` — {profit:.1f}% ({wins}W/{losses}L)\n"
        
        if stats['total'] == 0:
            msg = "📊 **Статистика пуста**\n\nСигналов пока не было или они ещё отслеживаются (нужно 60 мин после сигнала)."
        
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

    async def run(self):
        """Запуск бота"""
        await self.start_session()
        
        self.app = Application.builder().token(self.telegram_token).build()
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("listing", self.listing_command))
        self.app.add_handler(CommandHandler("test", self.test_command))
        
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        
        logger.info("✅ Telegram бот запущен (TURBO: 1.5s)")
        
        await self.app.bot.send_message(
            chat_id=self.chat_id,
            text="🟢 **MMR TURBO запущен!**\n\n• Памп детекция: 1.5с\n• Листинг детекция: 30с\n• /stats - статистика",
            parse_mode='Markdown'
        )
        
        # Запускаем детектор листингов в фоне
        listing_task = asyncio.create_task(self.listing_detector.run())
        
        # Запускаем трекер сигналов в фоне
        tracker_task = asyncio.create_task(self.signal_tracker.run())
        
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
