"""
НОВАЯ ВЕРСИЯ: REST-based Pump Detector
Опрашивает MEXC каждые 30 секунд через REST API
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
from logger import setup_logging, get_logger

logger = setup_logging()


class RestPumpDetector:
    """REST-based детектор пампов"""
    
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
        
        # Хранилище данных
        self.price_snapshots = defaultdict(list)  # symbol -> [(timestamp, price, volume), ...]
        self.last_prices = {}  # symbol -> last_price
        
        # Статистика
        self.pump_count = 0
        self.signal_count = 0
        self.scan_count = 0
        
        # Cooldown для предотвращения спама по одной монете
        self.pump_cooldown = {}  # symbol -> last_pump_notification_timestamp
        self.signal_cooldown = {}  # symbol -> last_signal_timestamp  
        self.cooldown_minutes = 2  # Минимум 2 минуты между уведомлениями на одну монету
        
        # Параметры детекции
        self.min_pump_pct = self.config['pump_detection']['min_price_increase_pct']
        self.timeframe_minutes = self.config['pump_detection']['timeframe_minutes']
        self.scan_interval = 2.5  # Опрос каждые 2.5 секунды - УЛЬТРА БЫСТРО
        
        logger.info("🔄 REST Pump Detector инициализирован")
    
    async def get_all_symbols(self) -> List[str]:
        """Получить все фьючерсные пары"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/v1/contract/detail"
                async with session.get(url) as response:
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
            return False, 0, 0
        
        snapshots = self.price_snapshots[symbol]
        if len(snapshots) < 2:
            return False, 0, 0
        
        # Берем данные за последние timeframe_minutes
        now = datetime.now()
        cutoff = now - timedelta(minutes=self.timeframe_minutes)
        recent = [s for s in snapshots if datetime.fromtimestamp(s[0]/1000) >= cutoff]
        
        if len(recent) < 2:
            return False, 0, 0
        
        # Расчет роста
        price_start = recent[0][1]
        
        # Находим пик и его время
        peak_snapshot = max(recent, key=lambda x: x[1])
        price_peak = peak_snapshot[1]
        peak_time = datetime.fromtimestamp(peak_snapshot[0]/1000)
        
        # Проверяем, когда был пик
        time_since_peak = (now - peak_time).total_seconds() / 60
        
        if price_start == 0:
            return False, 0, 0, ""
        
        increase_pct = ((price_peak - price_start) / price_start) * 100
        
        # Точное время роста (разница между первым и последним снапшотом)
        time_diff_seconds = (recent[-1][0] - recent[0][0]) / 1000
        time_diff_minutes = time_diff_seconds / 60
        if time_diff_minutes <= 0: time_diff_minutes = 0.1

    # Стратегии детекции
        is_pump = False
        pump_type = ""

        # 🔥 АГРЕССИВНОЕ ЛОГИРОВАНИЕ: >1% (по запросу)
        if increase_pct >= 1.0:
            logger.warning(f"📊 {symbol}: +{increase_pct:.2f}% за {time_diff_minutes:.1f}мин (пик {time_since_peak:.1f}мин назад)")

        # Увеличиваем окно, чтобы видеть даже старые пампы
        if time_since_peak > 30.0:
             return False, 0, 0, ""

        # 1. Основная: >1% (или из конфига)
        if increase_pct >= 1.0:
            is_pump = True
            pump_type = "MASSIVE"
        
        # 2. Быстрая: >1% за 5 мин
        elif increase_pct >= 1.0 and time_diff_minutes <= 5.0:
            is_pump = True
            pump_type = "FAST_IMPULSE"

        if is_pump:
            pump_emoji = "🚀" if pump_type == "MASSIVE" else "⚡️"
            logger.warning(f"{pump_type} {pump_emoji}: {symbol} +{increase_pct:.2f}% за {time_diff_minutes:.1f}мин ({price_start:.6f} → {price_peak:.6f})")
            return True, increase_pct, time_diff_minutes, pump_type

        return False, 0, 0, ""
    
    async def scan_market(self):
        """Сканирование рынка"""
        self.scan_count += 1
        
        logger.info(f"🔍 Сканирование #{self.scan_count}...")
        
        async with aiohttp.ClientSession() as session:
            # Получаем все тикеры
            tickers = await self.get_ticker_batch(session)
            
            if not tickers:
                logger.warning("⚠️ Не удалось получить тикеры")
                return
            
            logger.info(f"✅ Получено {len(tickers)} тикеров")
            
            # Обновляем снапшоты и детектируем пампы
            pumps_found = 0
            for symbol, ticker_data in tickers.items():
                price = ticker_data["last"]
                volume = ticker_data["volume"]
                timestamp = ticker_data["timestamp"]
                
                # Добавляем снапшот
                self.price_snapshots[symbol].append((timestamp, price, volume))
                
                # Чистим старые данные (старше 2 * timeframe)
                cutoff_time = timestamp - (self.timeframe_minutes * 2 * 60 * 1000)
                self.price_snapshots[symbol] = [
                    s for s in self.price_snapshots[symbol]
                    if s[0] > cutoff_time
                ]
                
                # Детектируем памп
                pump_result = self.detect_pump(symbol)
                if pump_result[0]:  # Если памп обнаружен
                    # Проверяем cooldown
                    now = datetime.now()
                    
                    # Логика уведомлений о пампе (чтобы не спамить в лог/чат)
                    should_notify = True
                    if symbol in self.pump_cooldown:
                        time_since_last = (now - self.pump_cooldown[symbol]).total_seconds() / 60
                        if time_since_last < self.cooldown_minutes:
                            should_notify = False
                            # logger.info(f"⏭️ {symbol}: Кулдаун уведомления еще {self.cooldown_minutes - time_since_last:.1f}мин")
                    
                    # Логика анализа (запускаем ВСЕГДА, если нет активного сигнала)
                    # Но проверяем, не отправляли ли мы уже СИГНАЛ недавно
                    if symbol in self.signal_cooldown:
                         time_since_signal = (now - self.signal_cooldown[symbol]).total_seconds() / 60
                         if time_since_signal < 30: # 30 минут кулдаун на СИГНАЛ
                             continue

                    pumps_found += 1
                    if should_notify:
                        self.pump_count += 1
                        self.pump_cooldown[symbol] = now
                    
                    increase_pct = pump_result[1]
                    time_minutes = pump_result[2]
                    
                    pump_type = pump_result[3]  # Тип пампа (MASSIVE или FAST_IMPULSE)
                    
                    # Создаем данные пампа
                    snapshots = self.price_snapshots[symbol]
                    cutoff = now - timedelta(minutes=self.timeframe_minutes)
                    recent = [s for s in snapshots if datetime.fromtimestamp(s[0]/1000) >= cutoff]
                    
                    if len(recent) < 2:
                        logger.warning(f"⚠️ {symbol}: Недостаточно снапшотов для создания pump_data ({len(recent)})")
                        continue
                    
                    logger.info(f"📊 {symbol}: Создаю pump_data (снапшотов: {len(recent)})")
                    
                    pump_data = {
                        "symbol": symbol,
                        "price_start": recent[0][1],
                        "price_peak": max(s[1] for s in recent),
                        "current_price": price,
                        "increase_pct": increase_pct,
                        "actual_time_minutes": time_minutes,  # Реальное время роста
                        "pump_type": pump_type,  # Тип пампа для адаптивных весов
                        "volume_spike": 1.5,
                        "volume_usd": volume * price,
                        "detected_at": datetime.now(),
                        "timeframe_minutes": self.timeframe_minutes
                    }
                    
                    # Отправляем уведомление только если кулдаун прошел
                    if should_notify:
                        await self.send_pump_alert(pump_data)
                    
                    # Запускаем анализ БЕЗ ЗАДЕРЖКИ - каждый скан!
                    try:
                        signal = await self.analyze_and_generate_signal(symbol, pump_data)
                        if signal:
                            # Сигнал успешно создан - устанавливаем кулдаун на сигнал
                            self.signal_cooldown[symbol] = now
                    except Exception as e:
                        logger.error(f"❌ ОШИБКА анализа {symbol}: {e}", exc_info=True)
            
            logger.info(f"📊 Сканирование завершено: {pumps_found} пампов обнаружено | Всего: {self.pump_count} пампов, {self.signal_count} сигналов")
    
    async def send_pump_alert(self, pump_data: Dict):
        """Отправить уведомление о пампе"""
        logger.warning(f"📢 ОТПРАВКА УВЕДОМЛЕНИЯ О ПАМПЕ: {pump_data['symbol']} +{pump_data['increase_pct']:.2f}%")
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
        logger.info(f"🔄 {symbol}: Выполняю анализ для SHORT сигнала...")
        
        try:
            # Получаем klines и orderbook
            logger.info(f"{symbol}: Запрашиваю klines и orderbook...")
            async with aiohttp.ClientSession() as session:
                # Klines
                klines_url = f"{self.rest_url}/api/v1/contract/kline/{symbol}"
                logger.info(f"{symbol}: Klines URL: {klines_url}?interval=Min1&limit=100")
                async with session.get(klines_url, params={"interval": "Min1", "limit": 100}) as resp:
                    klines = []
                    logger.info(f"{symbol}: Klines API статус: {resp.status}")
                    if resp.status == 200:
                        try:
                            data = await resp.json()
                            logger.info(f"{symbol}: Klines ответ - success: {data.get('success')}, тип data: {type(data.get('data'))}, длина: {len(data.get('data', [])) if isinstance(data.get('data'), list) else 'N/A'}")
                            
                            if data.get("success") and isinstance(data.get("data"), list):
                                for k in data.get("data", []):
                                    if not isinstance(k, dict):
                                        logger.warning(f"{symbol}: Kline элемент не словарь: {type(k)}")
                                        continue
                                    try:
                                        klines.append({
                                            "timestamp": k["time"],
                                            "open": float(k["open"]),
                                            "high": float(k["high"]),
                                            "low": float(k["low"]),
                                            "close": float(k["close"]),
                                            "volume": float(k["vol"])
                                        })
                                    except (KeyError, ValueError, TypeError) as e:
                                        logger.warning(f"{symbol}: Ошибка парсинга kline: {e}")
                                        continue
                                logger.info(f"{symbol}: Получено {len(klines)} свечей")
                            else:
                                logger.warning(f"{symbol}: Неверный формат klines данных - success={data.get('success')}, data={type(data.get('data'))}")
                        except Exception as e:
                            logger.error(f"{symbol}: Ошибка парсинга klines JSON: {e}")
                    else:
                        logger.warning(f"{symbol}: Klines API status={resp.status}")
                
                # Orderbook
                ob_url = f"{self.rest_url}/api/v1/contract/depth/{symbol}"
                async with session.get(ob_url, params={"limit": 20}) as resp:
                    orderbook = None
                    if resp.status == 200:
                        try:
                            data = await resp.json()
                            if data.get("success"):
                                orderbook = data.get("data")
                                logger.debug(f"{symbol}: Orderbook получен")
                            else:
                                logger.warning(f"{symbol}: Orderbook success=False")
                        except Exception as e:
                            logger.error(f"{symbol}: Ошибка парсинга orderbook JSON: {e}")
                    else:
                        logger.warning(f"{symbol}: Orderbook API status={resp.status}")
            
            # Fallback: если API не отдал klines, создаем их из наших снапшотов
            if not klines:
                logger.info(f"⚠️ {symbol}: MEXC API не отдал klines, создаю из price_snapshots...")
                
                if symbol in self.price_snapshots and len(self.price_snapshots[symbol]) >= 5:
                    snapshots = self.price_snapshots[symbol][-100:]  # Последние 100 снапшотов
                    
                    # Группируем по минутам
                    from collections import defaultdict
                    minute_data = defaultdict(list)
                    
                    for snap in snapshots:
                        timestamp_ms = snap[0]
                        price = snap[1]
                        volume = snap[2]
                        minute_key = int(timestamp_ms / 60000) * 60000  # Округляем до минуты
                        minute_data[minute_key].append((price, volume))
                    
                    # Создаем OHLCV свечи
                    for minute_ts in sorted(minute_data.keys()):
                        prices = [p[0] for p in minute_data[minute_ts]]
                        volumes = [p[1] for p in minute_data[minute_ts]]
                        
                        kline = {
                            "timestamp": minute_ts,
                            "open": prices[0],
                            "high": max(prices),
                            "low": min(prices),
                            "close": prices[-1],
                            "volume": sum(volumes) / len(volumes)  # Среднее
                        }
                        klines.append(kline)
                    
                    logger.info(f"✅ {symbol}: Создано {len(klines)} синтетических свечей из снапшотов")
                else:
                    logger.info(f"❌ {symbol}: Недостаточно данных для создания klines (снапшотов: {len(self.price_snapshots.get(symbol, []))})")
                    return
            
            if not klines:
                logger.error(f"❌ {symbol}: Не удалось получить klines ни из API, ни из снапшотов")
                return
            
            # История цен и объемов из снапшотов
            snapshots = self.price_snapshots[symbol][-100:]
            price_history = [s[1] for s in snapshots]
            volume_history = [s[2] for s in snapshots]
            
            # Генерируем сигнал
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
                logger.info(f"🎯 Сигнал #{self.signal_count} сгенерирован для {symbol}")
                
                # СНАЧАЛА отправляем сигнал в Telegram!
                msg = self.signal_generator.format_signal_message(signal)
                
                # Создаем кнопку для DexScreener
                keyboard = None
                if signal.get('dex_data'):
                    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                    dex_info = signal['dex_data']
                    # Правильный формат: https://dexscreener.com/chain/pair_address
                    dex_url = f"https://dexscreener.com/{dex_info['chain']}/{dex_info.get('pair_address', '')}"
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🦄 DexScreener", url=dex_url)]
                    ])
                
                await self.app.bot.send_message(
                    chat_id=self.chat_id,
                    text=msg,
                    parse_mode='Markdown',
                    reply_markup=keyboard,
                    disable_web_page_preview=True
                )
                logger.info(f"✅ Сигнал отправлен в Telegram: {symbol}")
                
                # Потом сохраняем в БД (не критично если упадет)
                try:
                    pump_id = self.db.add_pump(
                        symbol=pump_data['symbol'],
                        price_start=pump_data['price_start'],
                        price_peak=pump_data['price_peak'],
                        price_increase_pct=pump_data['increase_pct'],
                        volume_spike=pump_data['volume_spike'],
                        timeframe_minutes=pump_data['timeframe_minutes']
                    )
                    
                    signal_id = self.db.add_signal(
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
                except Exception as db_err:
                    logger.warning(f"⚠️ Ошибка сохранения в БД: {db_err}")
                
                return signal  # Возвращаем сигнал для учета cooldown
            else:
                logger.warning(f"⚠️ {symbol}: Сигнал не прошел проверку")
                return None
        
        except Exception as e:
            logger.error(f"❌ ОШИБКА генерации сигнала для {symbol}: {e}", exc_info=True)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        await update.message.reply_text(
            "🤖 **REST Pump Detector**\n\n"
            "Сканирует рынок каждые 30 секунд\n"
            "/status - статус\n"
            "/stats - статистика",
            parse_mode='Markdown'
        )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /status"""
        msg = f"""
📊 **Статус**

Сканирований: {self.scan_count}
Пампов найдено: {self.pump_count}
Сигналов: {self.signal_count}

Интервал сканирования: {self.scan_interval}с
Мин. рост: {self.min_pump_pct}%
Таймфрейм: {self.timeframe_minutes}мин
"""
        await update.message.reply_text(msg, parse_mode='Markdown')

    async def listing_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /listing - проверка новых листингов"""
        status_msg = await update.message.reply_text("🔄 Сканирую анонсы MEXC и проверяю биржи...")
        
        try:
            from exchange_checker import ExchangeChecker
            from mexc_scraper import MexcScraper
            
            checker = ExchangeChecker()
            scraper = MexcScraper()
            
            # 1. Получаем анонсы листингов
            listings = await scraper.get_new_listings()
            
            # Если скрапер не вернул данных
            if not listings:
                await status_msg.edit_text("⚠️ Не удалось получить календарь будущих листингов (защита сайта).\nИспользуйте `/check SYMBOL` для ручной проверки конкретной монеты.", parse_mode='Markdown')
                return
            
            # Формируем сообщение
            msg = "📅 **Календарь Листингов MEXC**\n\n"
            
            for item in listings[:5]: # Топ-5
                symbol = item['symbol']
                pair = item['pair']
                time_str = item['time_str']
                
                msg += f"🚀 **{pair}**\n"
                msg += f"⏰ {time_str}\n"
                msg += f"🔎 **Поиск на биржах:**\n"
                
                # Проверяем на других биржах
                exchanges = await checker.check_all_exchanges(symbol)
                
                # Binance
                if exchanges['Binance']:
                    msg += f"✅ [Binance]({exchanges['Binance']}) | "
                else:
                    msg += f"❌ Binance | "
                
                # Bybit
                if exchanges['Bybit']:
                    msg += f"✅ [Bybit]({exchanges['Bybit']}) | "
                else:
                    msg += f"❌ Bybit | "
                    
                # Gate
                if exchanges['Gate']:
                    msg += f"✅ [Gate]({exchanges['Gate']})\n\n"
                else:
                    msg += f"❌ Gate\n\n"
            
            await status_msg.edit_text(msg, parse_mode='Markdown', disable_web_page_preview=True)
            
        except Exception as e:
            logger.error(f"Ошибка /listing: {e}")
            await status_msg.edit_text(f"❌ Произошла ошибка: {e}")

    async def listing_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /listing - календарь листингов"""
        status_msg = await update.message.reply_text("� Сканирую анонсы MEXC и проверяю биржи...")
        
        try:
            from exchange_checker import ExchangeChecker
            from mexc_scraper import MexcScraper
            
            checker = ExchangeChecker()
            scraper = MexcScraper()
            
            # 1. Получаем анонсы листингов
            listings = await scraper.get_new_listings()
            
            if not listings:
                await status_msg.edit_text("⚠️ Не удалось получить календарь будущих листингов (защита сайта).", parse_mode='Markdown')
                return
            
            # Формируем сообщение
            msg = "📅 **Календарь Листингов MEXC**\n\n"
            
            for item in listings[:5]: # Топ-5
                symbol = item['symbol']
                pair = item['pair']
                time_str = item['time_str']
                
                msg += f"🚀 **{pair}**\n"
                msg += f"⏰ {time_str}\n"
                msg += f"🔎 **Поиск на биржах:**\n"
                
                # Проверяем на других биржах
                exchanges = await checker.check_all_exchanges(symbol)
                
                # Binance
                if exchanges['Binance']:
                    msg += f"✅ [Binance]({exchanges['Binance']}) | "
                else:
                    msg += f"❌ Binance | "
                
                # Bybit
                if exchanges['Bybit']:
                    msg += f"✅ [Bybit]({exchanges['Bybit']}) | "
                else:
                    msg += f"❌ Bybit | "
                    
                # Gate
                if exchanges['Gate']:
                    msg += f"✅ [Gate]({exchanges['Gate']})\n\n"
                else:
                    msg += f"❌ Gate\n\n"
            
            await status_msg.edit_text(msg, parse_mode='Markdown', disable_web_page_preview=True)
            
        except Exception as e:
            logger.error(f"Ошибка /listing: {e}")
            await status_msg.edit_text(f"❌ Произошла ошибка: {e}")

    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тестовый сигнал для проверки формата"""
        await update.message.reply_text("🧪 Генерирую тестовый сигнал...")
        
        # Создаем фейковый сигнал
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
        # Telegram
        self.app = Application.builder().token(self.telegram_token).build()
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("listing", self.listing_command))
        self.app.add_handler(CommandHandler("test", self.test_command))
        
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        
        logger.info("✅ Telegram бот запущен")
        
        # Приветствие
        await self.app.bot.send_message(
            chat_id=self.chat_id,
            text="🟢 **MMR запущен!**\n\nСканирование запущено",
            parse_mode='Markdown'
        )
        
        # Основной цикл сканирования
        try:
            while True:
                await self.scan_market()
                await asyncio.sleep(self.scan_interval)
        
        except KeyboardInterrupt:
            logger.info("Остановка...")
        finally:
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
