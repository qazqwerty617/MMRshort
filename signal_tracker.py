"""
Signal Tracker - отслеживает результаты сигналов
Проверяет цену через 5/15/60 минут и записывает win/loss
Обучает historical_pattern_analyzer на реальных данных
"""

import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
from logger import get_logger

logger = get_logger()


class SignalTracker:
    """Трекер результатов сигналов"""
    
    def __init__(self, rest_url: str = "https://contract.mexc.com"):
        self.rest_url = rest_url
        
        # Активные сигналы для отслеживания
        # signal_id -> {symbol, entry_price, peak_price, pump_pct, created_at, checked_5m, checked_15m, checked_60m}
        self.active_signals: Dict[str, dict] = {}
        
        # Результаты сигналов
        self.signal_results: List[dict] = []
        
        # Callback для обучения паттернов
        self.on_result_callback = None
        
        # Callback для уведомлений
        self.on_notification_callback = None
        
        self.running = False
        self.check_interval = 60  # Проверка каждую минуту
    
    def add_signal(self, symbol: str, entry_price: float, peak_price: float, pump_pct: float):
        """Добавить сигнал для отслеживания"""
        signal_id = f"{symbol}_{datetime.now().timestamp()}"
        
        self.active_signals[signal_id] = {
            'signal_id': signal_id,
            'symbol': symbol,
            'entry_price': entry_price,
            'peak_price': peak_price,
            'pump_pct': pump_pct,
            'created_at': datetime.now(),
            'checked_5m': False,
            'checked_15m': False,
            'checked_60m': False,
            'price_5m': None,
            'price_15m': None,
            'price_60m': None,
            'result': None,  # 'win' / 'loss' / None
        }
        
        logger.info(f"📊 Трекер: добавлен сигнал {symbol} @ {entry_price:.8f}")
        return signal_id
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Получить текущую цену"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/v1/contract/ticker"
                params = {"symbol": symbol}
                
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('success') and data.get('data'):
                            return float(data['data'].get('lastPrice', 0))
        except Exception as e:
            logger.error(f"Ошибка получения цены {symbol}: {e}")
        return None
    
    async def check_signals(self):
        """Проверить все активные сигналы"""
        now = datetime.now()
        completed_signals = []
        
        for signal_id, signal in self.active_signals.items():
            created = signal['created_at']
            symbol = signal['symbol']
            entry_price = signal['entry_price']
            peak_price = signal['peak_price']
            
            time_elapsed = (now - created).total_seconds() / 60  # минуты
            
            # Проверка через 5 минут
            if time_elapsed >= 5 and not signal['checked_5m']:
                price = await self.get_current_price(symbol)
                if price:
                    signal['price_5m'] = price
                    signal['checked_5m'] = True
                    drop_pct = ((peak_price - price) / peak_price) * 100
                    logger.info(f"📉 {symbol} 5мин: {price:.8f} (падение {drop_pct:.1f}% от пика)")
            
            # Проверка через 15 минут
            if time_elapsed >= 15 and not signal['checked_15m']:
                price = await self.get_current_price(symbol)
                if price:
                    signal['price_15m'] = price
                    signal['checked_15m'] = True
                    drop_pct = ((peak_price - price) / peak_price) * 100
                    logger.info(f"📉 {symbol} 15мин: {price:.8f} (падение {drop_pct:.1f}% от пика)")
            
            # Проверка через 60 минут - финальная
            if time_elapsed >= 60 and not signal['checked_60m']:
                price = await self.get_current_price(symbol)
                if price:
                    signal['price_60m'] = price
                    signal['checked_60m'] = True
                    
                    # Определяем результат
                    # WIN: цена упала от входа (шорт прибыльный)
                    # LOSS: цена выше входа
                    profit_pct = ((entry_price - price) / entry_price) * 100
                    
                    if profit_pct > 0:
                        signal['result'] = 'win'
                        signal['profit_pct'] = profit_pct
                        logger.warning(f"✅ {symbol}: WIN +{profit_pct:.1f}%")
                    else:
                        signal['result'] = 'loss'
                        signal['profit_pct'] = profit_pct
                        logger.warning(f"❌ {symbol}: LOSS {profit_pct:.1f}%")
                    
                    # Записываем результат
                    self.signal_results.append(signal.copy())
                    
                    # Вызываем callback для обучения паттерна
                    if self.on_result_callback:
                        await self.on_result_callback(signal)
                    
                    # Отправляем уведомление
                    if self.on_notification_callback:
                        await self.on_notification_callback(signal)
                    
                    completed_signals.append(signal_id)
        
        # Удаляем завершённые сигналы
        for signal_id in completed_signals:
            del self.active_signals[signal_id]
    
    def get_statistics(self) -> dict:
        """Получить статистику по сигналам"""
        if not self.signal_results:
            return {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0}
        
        wins = sum(1 for s in self.signal_results if s.get('result') == 'win')
        losses = sum(1 for s in self.signal_results if s.get('result') == 'loss')
        total = wins + losses
        
        avg_profit = 0
        if self.signal_results:
            profits = [s.get('profit_pct', 0) for s in self.signal_results if s.get('profit_pct')]
            if profits:
                avg_profit = sum(profits) / len(profits)
        
        return {
            'total': total,
            'wins': wins,
            'losses': losses,
            'win_rate': (wins / total * 100) if total > 0 else 0,
            'avg_profit': avg_profit,
            'active_tracking': len(self.active_signals)
        }
    
    async def run(self):
        """Запустить фоновую проверку сигналов"""
        self.running = True
        logger.info("📊 Signal Tracker запущен")
        
        while self.running:
            try:
                if self.active_signals:
                    await self.check_signals()
            except Exception as e:
                logger.error(f"Ошибка Signal Tracker: {e}")
            
            await asyncio.sleep(self.check_interval)
    
    def stop(self):
        self.running = False
