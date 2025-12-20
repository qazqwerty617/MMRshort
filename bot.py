"""
MEXC Pump Detector Bot - главный модуль Telegram бота
Бот для обнаружения пампов на MEXC и генерации сигналов на шорт
"""

import asyncio
import yaml
import os
from datetime import datetime
from typing import Dict, Optional, List
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from mexc_client import MEXCClient
from pump_detector import PumpDetector
from signal_generator import SignalGenerator
from database import Database
from coin_profiler import CoinProfiler
from listing_tracker import ListingTracker, CrossExchangeChecker
from logger import setup_logging, get_logger

# Инициализация логгера
logger = setup_logging()


class PumpDetectorBot:
    """Главный класс Telegram бота"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Инициализация бота
        
        Args:
            config_path: Путь к файлу конфигурации
        """
        # Загрузка конфигурации
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        # Инициализация компонентов
        self.db = Database(self.config['database']['path'])
        self.mexc = MEXCClient(self.config['mexc'])
        self.pump_detector = PumpDetector(self.config['pump_detection'])
        self.coin_profiler = CoinProfiler(self.db, self.config['learning'])
        self.signal_generator = SignalGenerator(self.config, self.coin_profiler)
        self.listing_tracker = ListingTracker(self.mexc)
        self.cross_exchange = CrossExchangeChecker()
        
        # Telegram
        self.telegram_token = self.config['telegram']['bot_token']
        self.chat_id = self.config['telegram']['chat_id']
        self.app = None
        
        # Кэш активных мониторингов
        self.monitored_symbols = set()
        self.pump_cooldown = {}  # Для избежания повторных сигналов
        self.ticker_count = 0    # Счетчик обновлений
        self.pump_count = 0      # Счетчик обнаруженных пампов
        self.signal_count = 0    # Счетчик сгенерированных сигналов
        self.last_heartbeat = datetime.now()
        
        logger.info("Pump Detector Bot инициализирован")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        welcome_msg = """
🤖 **MEXC Pump Detector Bot**

Бот для обнаружения аномальных пампов на MEXC и генерации сигналов на шорт.

**Команды:**
/start - Показать это сообщение
/status - Статус бота и статистика
/stats - Статистика по сигналам
/listing - Новые листинги сегодня
/help - Помощь

Бот работает автоматически и будет присылать сигналы в этот чат.
"""
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
        logger.info(f"Команда /start от {update.effective_user.id}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /status"""
        status_msg = f"""
📊 **Статус бота**

🔌 WebSocket: {'✅ Подключен' if self.mexc.running else '❌ Отключен'}
👀 Мониторинг: {len(self.monitored_symbols)} пар
🕐 Время работы: с {datetime.now().strftime('%H:%M:%S')}

⚙️ **Параметры обнаружения:**
Минимальный памп: +{self.config['pump_detection']['min_price_increase_pct']}%
Таймфрейм: {self.config['pump_detection']['timeframe_minutes']} мин
Множитель объёма: {self.config['pump_detection']['min_volume_spike']}x

🎯 **Параметры сигналов:**
Мин. качество: {self.config['signal']['min_quality_score']}/10
Мин. R/R: {self.config['signal']['min_risk_reward']}

🧠 **Обучение:** {'✅ Включено' if self.config['learning']['enabled'] else '❌ Выключено'}
"""
        await update.message.reply_text(status_msg, parse_mode='Markdown')
        logger.info(f"Команда /status от {update.effective_user.id}")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /stats"""
        stats = self.db.get_statistics()
        
        total_signals = stats.get('total_signals', 0)
        profitable = stats.get('profitable_signals', 0)
        avg_quality = stats.get('avg_quality', 0)
        
        win_rate = (profitable / total_signals * 100) if total_signals > 0 else 0
        
        stats_msg = f"""
📈 **Статистика сигналов**

Всего сигналов: {total_signals}
Прибыльных: {profitable}
Win Rate: {win_rate:.1f}%

Средн. качество: {avg_quality:.1f}/10
        """
        
        await update.message.reply_text(stats_msg, parse_mode='Markdown')
        logger.info(f"Команда /stats от {update.effective_user.id}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        help_msg = """
❓ **Помощь**

**Как работает бот:**
1. Подключается ко всем фьючерсным парам MEXC
2. Отслеживает аномальные пампы (резкий рост цены + объёма)
3. При обнаружении пампа начинает анализ для входа в шорт
4. Ищет: дивергенцию, падение объёма, сопротивление в ордербуке
5. Генерирует сигнал с точкой входа, SL и TP

**Система обучения:**
Бот запоминает исходы всех сигналов и адаптирует стратегию для каждой монеты отдельно.

**Важно:**
⚠️ Это только сигналы, не финансовый совет
⚠️ Всегда проверяйте сигналы перед входом
⚠️ Используйте риск-менеджмент
"""
        await update.message.reply_text(help_msg, parse_mode='Markdown')
    
    async def listing_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /listing"""
        listings = self.listing_tracker.get_todays_listings()
        
        if not listings:
            msg = "📊 **Новые листинги**\n\nСегодня новых листингов на MEXC нет."
            await update.message.reply_text(msg, parse_mode='Markdown')
            return
        
        msg = f"📊 **Новые листинги на MEXC ({len(listings)})**\n\n"
        
        for listing in listings:
            symbol = listing['symbol']
            time = listing['detected_at'].strftime('%H:%M')
            
            # Проверяем на других биржах
            exchange_status = await self.cross_exchange.check_exchanges(symbol)
            status_text = self.cross_exchange.format_exchange_status(exchange_status)
            
            # Определяем эксклюзивность
            is_exclusive = not any(exchange_status.values())
            exclusive_badge = " 🔥 ЭКСКЛЮЗИВ!" if is_exclusive else ""
            
            msg += f"**{symbol}**{exclusive_badge}\n"
            msg += f"Время: {time}\n"
            msg += f"{status_text}\n\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
        logger.info(f"Команда /listing от {update.effective_user.id}")
    
    async def send_pump_alert(self, pump_data: Dict):
        """Отправить уведомление о пампе"""
        try:
            msg = f"""
🚀 **ПАМП ОБНАРУЖЕН**

Пара: `{pump_data['symbol']}`
Рост: +{pump_data['increase_pct']:.1f}% за {pump_data['timeframe_minutes']}мин
Всплеск объёма: {pump_data['volume_spike']:.1f}x
Цена: {pump_data['price_start']:.8f} → {pump_data['price_peak']:.8f}

⏳ Начинаю анализ для входа в шорт...
"""
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=msg,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления о пампе: {e}")
    
    async def send_signal(self, signal: Dict):
        """Отправить сигнал"""
        try:
            msg = self.signal_generator.format_signal_message(signal)
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=msg,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки сигнала: {e}")
    
    async def on_ticker_update(self, data: Dict):
        """Обработчик обновления тикера"""
        self.ticker_count += 1
        symbol = data['symbol']
        price = data['price']
        volume = data['volume']
        timestamp = data['timestamp']
        
        # Добавляем данные в детектор
        self.pump_detector.add_price_data(symbol, price, volume, timestamp)
        
        # 🔥 ЭКСТРА-ТЕСТ: Принудительно создаем ФЕЙКОВЫЙ памп на BTC_USDT после накопления данных
        if symbol == 'BTC_USDT' and self.pump_count == 0:
            price_history = self.pump_detector.get_price_history(symbol)
            if len(price_history) >= 10:  # Достаточно данных накоплено
                logger.warning(f"🧪 ТЕСТОВЫЙ РЕЖИМ: Принудительно создаем ФЕЙКОВЫЙ памп на {symbol}")
                
                fake_pump = {
                    "symbol": symbol,
                    "price_start": price * 0.999,
                    "price_peak": price * 1.001,
                    "current_price": price,
                    "increase_pct": 0.2,  # 0.2% фейковый рост
                    "volume_spike": 1.5,
                    "volume_usd": 5000,
                    "detected_at": datetime.now(),
                    "timeframe_minutes": 5
                }
                
                self.pump_cooldown[symbol] = datetime.now()
                self.pump_count += 1
                
                pump_id = self.db.add_pump(
                    symbol=fake_pump['symbol'],
                    price_start=fake_pump['price_start'],
                    price_peak=fake_pump['price_peak'],
                    price_increase_pct=fake_pump['increase_pct'],
                    volume_spike=fake_pump['volume_spike'],
                    timeframe_minutes=fake_pump['timeframe_minutes']
                )
                
                self.coin_profiler.update_coin_statistics(symbol, fake_pump)
                await self.send_pump_alert(fake_pump)
                asyncio.create_task(self.analyze_and_generate_signal(pump_id, fake_pump))
                return
        
        # Проверяем памп
        pump = self.pump_detector.detect_pump(symbol)
        
        if pump:
            # Проверяем cooldown (чтобы не спамить по одному пампу)
            if symbol in self.pump_cooldown:
                last_pump_time = self.pump_cooldown[symbol]
                if (datetime.now() - last_pump_time).seconds < 600:  # 10 минут
                    return
            
            self.pump_cooldown[symbol] = datetime.now()
            self.pump_count += 1  # Увеличиваем счетчик пампов
            
            # Сохраняем памп в БД
            pump_id = self.db.add_pump(
                symbol=pump['symbol'],
                price_start=pump['price_start'],
                price_peak=pump['price_peak'],
                price_increase_pct=pump['increase_pct'],
                volume_spike=pump['volume_spike'],
                timeframe_minutes=pump['timeframe_minutes']
            )
            
            # Обновляем статистику монеты
            self.coin_profiler.update_coin_statistics(symbol, pump)
            
            # Отправляем уведомление
            await self.send_pump_alert(pump)
            
            # Запускаем анализ для генерации сигнала
            asyncio.create_task(self.analyze_and_generate_signal(pump_id, pump))
    
    async def analyze_and_generate_signal(self, pump_id: int, pump_data: Dict):
        """Анализировать памп и сгенерировать сигнал"""
        symbol = pump_data['symbol']
        
        logger.info(f"🔍 Начинаем анализ {symbol} для генерации сигнала...")
        
        # Ждём несколько секунд для сбора данных
        await asyncio.sleep(10)
        
        try:
            # Получаем исторические данные
            klines = await self.mexc.get_klines(symbol, interval="Min1", limit=100)
            orderbook = await self.mexc.get_orderbook(symbol, limit=20)
            
            if not klines:
                logger.warning(f"{symbol}: Не удалось получить klines")
                return
            
            price_history = self.pump_detector.get_price_history(symbol)
            volume_history = self.pump_detector.get_volume_history(symbol)
            
            # Генерируем сигнал
            signal = await self.signal_generator.generate_signal(
                symbol=symbol,
                pump_data=pump_data,
                price_history=price_history,
                volume_history=volume_history,
                klines=klines,
                orderbook=orderbook,
                mexc_client=self.mexc  # Передаём MEXC клиент для funding rate и MTF
            )
            
            if signal:
                self.signal_count += 1  # Увеличиваем счетчик сигналов
                logger.info(f"🎯 Сигнал #{self.signal_count} успешно сгенерирован для {symbol}")
                
                # Сохраняем сигнал в БД
                signal_id = self.db.add_signal(
                    pump_id=pump_id,
                    symbol=symbol,
                    entry_price=signal['entry_price'],
                    stop_loss=signal['stop_loss'],
                    take_profits=signal['take_profits'],
                    risk_reward=signal['risk_reward_ratio'],
                    quality_score=signal['quality_score'],
                    factors=signal['factors'],
                    weights=signal['weights']
                )
                
                # Отправляем сигнал
                await self.send_signal(signal)
                
                # Запускаем отслеживание исхода
                asyncio.create_task(self.track_signal_outcome(signal_id, symbol))
            else:
                logger.warning(f"⚠️ {symbol}: Сигнал не прошел проверку качества (см. логи выше)")
        
        except Exception as e:
            logger.error(f"Ошибка генерации сигнала для {symbol}: {e}")
    
    async def track_signal_outcome(self, signal_id: int, symbol: str):
        """Отслеживать исход сигнала"""
        tracking_periods = self.config['learning']['tracking_periods']
        
        for minutes in tracking_periods:
            await asyncio.sleep(minutes * 60)
            
            # Получаем текущую цену
            current_price = self.mexc.get_current_price(symbol)
            
            if current_price:
                # Обновляем БД
                if minutes == 5:
                    self.db.update_signal_outcome(signal_id, price_5m=current_price)
                elif minutes == 15:
                    self.db.update_signal_outcome(signal_id, price_15m=current_price)
                elif minutes == 60:
                    self.db.update_signal_outcome(signal_id, price_1h=current_price)
                elif minutes == 240:
                    self.db.update_signal_outcome(signal_id, price_4h=current_price)
        
        # После отслеживания - обучаемся на результате
        self.coin_profiler.learn_from_signal_outcome(signal_id)
    
    async def start_monitoring(self):
        """Начать мониторинг всех пар"""
        try:
            # Подключаемся к WebSocket
            await self.mexc.connect()
            
            # Получаем список всех пар
            symbols = await self.mexc.get_all_symbols()
            
            if not symbols:
                logger.error("Не удалось получить список пар")
                return
            
            logger.info(f"Получено {len(symbols)} пар для мониторинга")
            
            # Инициализируем listing tracker с текущими парами
            await self.listing_tracker.initialize()
            
            # Регистрируем колбэк для тикеров
            self.mexc.on('ticker', self.on_ticker_update)
            
            # Подписываемся на ВСЕ тикеры без ограничений
            monitor_config = self.config['monitoring']
            ignore_patterns = monitor_config.get('ignore_patterns', [])
            
            subscribed_count = 0
            for symbol in symbols:  # Убрали [:max_pairs] - мониторим ВСЕ пары
                # Проверяем игнор-паттерны (если они есть)
                skip = False
                if ignore_patterns:
                    for pattern in ignore_patterns:
                        import re
                        if re.match(pattern, symbol):
                            skip = True
                            break
                
                if skip:
                    logger.debug(f"Пропускаем {symbol} (ignore pattern)")
                    continue
                
                await self.mexc.subscribe_ticker(symbol)
                self.monitored_symbols.add(symbol)
                subscribed_count += 1
                await asyncio.sleep(0.1)
            
            logger.info(f"✅ Начат мониторинг {subscribed_count} пар (из {len(symbols)} доступных)")
            
            # Запускаем периодическую проверку новых листингов (каждые 5 минут)
            asyncio.create_task(self.periodic_listing_check())
        
        except Exception as e:
            logger.error(f"Ошибка запуска мониторинга: {e}")
            raise
    
    async def periodic_listing_check(self):
        """Периодическая проверка новых листингов"""
        while True:
            try:
                await asyncio.sleep(300)  # Каждые 5 минут
                
                # Очищаем старые листинги
                self.listing_tracker.clear_old_listings()
                
                # Проверяем новые
                new_symbols = await self.listing_tracker.check_for_new_listings()
                
                if new_symbols:
                    # Отправляем уведомление о новых листингах
                    await self.notify_new_listing(new_symbols)
                    
                    # Автоматически подписываемся на новые пары
                    for symbol in new_symbols:
                        try:
                            await self.mexc.subscribe_ticker(symbol)
                            self.monitored_symbols.add(symbol)
                            logger.info(f"✅ Автоподписка на новый листинг: {symbol}")
                        except Exception as e:
                            logger.error(f"Ошибка подписки на {symbol}: {e}")
            
            except Exception as e:
                logger.error(f"Ошибка periodic listing check: {e}")
    
    async def notify_new_listing(self, new_symbols: List[str]):
        """Уведомить о новых листингах"""
        try:
            for symbol in new_symbols:
                # Проверяем на других биржах
                exchange_status = await self.cross_exchange.check_exchanges(symbol)
                status_text = self.cross_exchange.format_exchange_status(exchange_status)
                
                is_exclusive = not any(exchange_status.values())
                exclusive_badge = " 🔥 ЭКСКЛЮЗИВ MEXC!" if is_exclusive else ""
                
                msg = f"""
🆕 **НОВЫЙ ЛИСТИНГ{exclusive_badge}**

**Пара:** `{symbol}`
**Биржа:** MEXC Futures
**Время:** {datetime.now().strftime('%H:%M:%S')}

📊 **Наличие на других биржах:**
{status_text}

⚡ Бот автоматически начал мониторинг этой пары!
"""
                
                await self.app.bot.send_message(
                    chat_id=self.chat_id,
                    text=msg,
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления о листинге: {e}")

    async def run(self):
        """Запустить бота"""
        # Создаём Telegram приложение
        self.app = Application.builder().token(self.telegram_token).build()
        
        # Регистрируем команды
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("listing", self.listing_command))
        
        # Запускаем Telegram бота
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        
        logger.info("Telegram бот запущен")
        
        # Отправляем приветственное сообщение
        try:
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text="🟢 **Бот запущен и начинает мониторинг MEXC!**",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки приветствия: {e}")
        
        # Запускаем мониторинг
        await self.start_monitoring()
        
        # Держим бота запущенным
        try:
            while True:
                await asyncio.sleep(1)
                
                # Heartbeat раз в 60 секунд
                if (datetime.now() - self.last_heartbeat).seconds >= 60:
                    if self.ticker_count > 0:
                        logger.info(f"💓 Heartbeat: {self.ticker_count} тикеров/мин | Пампов: {self.pump_count} | Сигналов: {self.signal_count}")
                        self.ticker_count = 0
                    else:
                        logger.warning("⚠️ Heartbeat: Нет обновлений цен! Проверьте соединение.")
                    
                    self.last_heartbeat = datetime.now()
                    
        except KeyboardInterrupt:
            logger.info("Получен сигнал остановки")
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Остановить бота"""
        logger.info("Останавливаем бота...")
        
        await self.mexc.disconnect()
        
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        
        logger.info("Бот остановлен")


async def main():
    """Главная функция"""
    # Создаём директории если их нет
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    bot = PumpDetectorBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
