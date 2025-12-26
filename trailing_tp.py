"""
📈 TRAILING TP TRACKER v1.0 - Динамический трейлинг для максимизации профита

ФИЛОСОФИЯ:
Вместо фиксированных TP1/TP2/TP3, trailing TP "следует" за ценой,
фиксируя профит когда цена разворачивается.

ПРЕИМУЩЕСТВА:
- Ловит весь дамп, а не фиксированный %
- Минимизирует преждевременное закрытие
- Защищает накопленный профит
"""

import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class TrailingTPTracker:
    """
    📈 TRAILING TAKE PROFIT TRACKER
    
    Отслеживает цену после открытия шорта и:
    1. Активирует trailing после достижения минимального профита
    2. Следует за ценой на заданном расстоянии
    3. Закрывает когда цена разворачивается
    """
    
    def __init__(self, rest_url: str = "https://contract.mexc.com"):
        self.rest_url = rest_url
        
        # Активные трейлинги: signal_id -> TrailingState
        self.active_trails: Dict[str, dict] = {}
        
        # Настройки
        self.activation_profit_pct = 2.0   # Активация после -2% (профита для шорта)
        self.trail_distance_pct = 1.0      # Расстояние trailing от low
        self.max_tracking_minutes = 240     # Макс. время отслеживания (4 часа)
        self.check_interval_sec = 5         # Частота проверки цены
        
        # Callbacks
        self.on_tp_hit: Optional[Callable] = None      # Когда trailing TP сработал
        self.on_new_low: Optional[Callable] = None     # Когда достигнут новый low
        
        self.running = False
        self.session = None
    
    def add_position(self, signal_id: str, symbol: str, entry_price: float,
                    sl_price: float, initial_tps: List[float] = None) -> bool:
        """
        Добавить позицию для trailing отслеживания.
        
        Args:
            signal_id: Уникальный ID сигнала
            symbol: Символ (например 'BTC_USDT')
            entry_price: Цена входа
            sl_price: Stop Loss цена
            initial_tps: Начальные TP уровни [tp1, tp2, tp3]
        
        Returns:
            bool: Успешно ли добавлено
        """
        if signal_id in self.active_trails:
            logger.warning(f"Trailing уже существует для {signal_id}")
            return False
        
        self.active_trails[signal_id] = {
            'signal_id': signal_id,
            'symbol': symbol,
            'entry_price': entry_price,
            'sl_price': sl_price,
            'initial_tps': initial_tps or [],
            
            # Trailing state
            'lowest_price': entry_price,      # Минимальная достигнутая цена
            'trailing_tp': None,              # Текущий trailing TP уровень
            'is_activated': False,            # Активирован ли trailing
            'activation_price': None,         # Цена активации
            
            # Время
            'created_at': datetime.now(),
            'last_check': datetime.now(),
            
            # Результаты
            'current_price': entry_price,
            'max_profit_pct': 0,
            'status': 'TRACKING',  # TRACKING, TP_HIT, SL_HIT, EXPIRED
            
            # История (для анализа)
            'price_history': [],
        }
        
        logger.info(f"📈 Trailing добавлен: {symbol} @ {entry_price:.8f}")
        return True
    
    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Получить текущую цену."""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            url = f"{self.rest_url}/api/v1/contract/ticker"
            params = {"symbol": symbol}
            
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('success') and data.get('data'):
                        return float(data['data'].get('lastPrice', 0))
        except Exception as e:
            logger.debug(f"Ошибка получения цены {symbol}: {e}")
        return None
    
    async def check_position(self, signal_id: str) -> Dict:
        """
        Проверить одну позицию.
        
        Returns:
            {
                'action': 'NONE' / 'NEW_LOW' / 'TP_HIT' / 'SL_HIT' / 'EXPIRED',
                'current_price': float,
                'profit_pct': float,
                'trailing_tp': float or None
            }
        """
        if signal_id not in self.active_trails:
            return {'action': 'NOT_FOUND'}
        
        trail = self.active_trails[signal_id]
        symbol = trail['symbol']
        entry = trail['entry_price']
        sl = trail['sl_price']
        
        # Получаем текущую цену
        price = await self.get_current_price(symbol)
        if not price:
            return {'action': 'PRICE_ERROR'}
        
        trail['current_price'] = price
        trail['last_check'] = datetime.now()
        trail['price_history'].append({'time': datetime.now(), 'price': price})
        
        # Ограничиваем историю
        if len(trail['price_history']) > 1000:
            trail['price_history'] = trail['price_history'][-500:]
        
        # Рассчитываем профит (для шорта: профит = вход - текущая)
        profit_pct = ((entry - price) / entry) * 100
        trail['max_profit_pct'] = max(trail['max_profit_pct'], profit_pct)
        
        result = {
            'action': 'NONE',
            'current_price': price,
            'profit_pct': profit_pct,
            'trailing_tp': trail['trailing_tp']
        }
        
        # Проверка SL (для шорта: SL выше входа)
        if price >= sl:
            trail['status'] = 'SL_HIT'
            result['action'] = 'SL_HIT'
            logger.warning(f"🛑 {symbol}: SL HIT @ {price:.8f}")
            return result
        
        # Проверка истечения
        elapsed = (datetime.now() - trail['created_at']).total_seconds() / 60
        if elapsed >= self.max_tracking_minutes:
            trail['status'] = 'EXPIRED'
            result['action'] = 'EXPIRED'
            logger.info(f"⏰ {symbol}: Tracking expired after {elapsed:.0f} min")
            return result
        
        # === TRAILING LOGIC ===
        
        # 1. Активация trailing (достигнут минимальный профит)
        if not trail['is_activated'] and profit_pct >= self.activation_profit_pct:
            trail['is_activated'] = True
            trail['activation_price'] = price
            trail['lowest_price'] = price
            trail['trailing_tp'] = price * (1 + self.trail_distance_pct / 100)
            
            logger.info(f"✅ {symbol}: Trailing ACTIVATED @ {price:.8f} (profit: {profit_pct:.1f}%)")
            result['action'] = 'ACTIVATED'
            result['trailing_tp'] = trail['trailing_tp']
        
        # 2. Обновление trailing (новый low)
        if trail['is_activated'] and price < trail['lowest_price']:
            old_low = trail['lowest_price']
            trail['lowest_price'] = price
            trail['trailing_tp'] = price * (1 + self.trail_distance_pct / 100)
            
            logger.info(f"📉 {symbol}: NEW LOW {old_low:.8f} → {price:.8f} | TP: {trail['trailing_tp']:.8f}")
            
            result['action'] = 'NEW_LOW'
            result['trailing_tp'] = trail['trailing_tp']
            
            if self.on_new_low:
                await self.on_new_low(trail, price, profit_pct)
        
        # 3. Проверка trailing TP hit (цена поднялась до trailing TP)
        if trail['is_activated'] and trail['trailing_tp'] and price >= trail['trailing_tp']:
            trail['status'] = 'TP_HIT'
            final_profit = ((entry - price) / entry) * 100
            
            logger.warning(f"🎯 {symbol}: TRAILING TP HIT @ {price:.8f} | Profit: {final_profit:.1f}%")
            
            result['action'] = 'TP_HIT'
            result['final_profit_pct'] = final_profit
            
            if self.on_tp_hit:
                await self.on_tp_hit(trail, price, final_profit)
        
        return result
    
    async def run(self):
        """Запустить фоновое отслеживание всех позиций."""
        self.running = True
        logger.info("📈 Trailing TP Tracker запущен")
        
        while self.running:
            try:
                # Копируем ключи чтобы избежать изменения dict во время итерации
                signal_ids = list(self.active_trails.keys())
                
                for signal_id in signal_ids:
                    if signal_id not in self.active_trails:
                        continue
                    
                    trail = self.active_trails[signal_id]
                    
                    # Пропускаем завершённые
                    if trail['status'] != 'TRACKING':
                        continue
                    
                    result = await self.check_position(signal_id)
                    
                    # Удаляем завершённые
                    if result['action'] in ['TP_HIT', 'SL_HIT', 'EXPIRED']:
                        # Сохраняем результат перед удалением
                        self._save_result(trail, result)
                        del self.active_trails[signal_id]
                
            except Exception as e:
                logger.error(f"Trailing tracker error: {e}")
            
            await asyncio.sleep(self.check_interval_sec)
    
    def _save_result(self, trail: Dict, result: Dict):
        """Сохранить результат трейлинга для анализа."""
        # Здесь можно добавить сохранение в БД
        logger.info(f"📊 Trailing Result: {trail['symbol']} | "
                   f"Entry: {trail['entry_price']:.8f} | "
                   f"Max Profit: {trail['max_profit_pct']:.1f}% | "
                   f"Final: {result.get('final_profit_pct', 0):.1f}% | "
                   f"Status: {result['action']}")
    
    def stop(self):
        """Остановить tracker."""
        self.running = False
        if self.session:
            asyncio.create_task(self.session.close())
    
    def get_status(self) -> Dict:
        """Получить статус всех активных trailing позиций."""
        active = []
        for signal_id, trail in self.active_trails.items():
            active.append({
                'symbol': trail['symbol'],
                'entry_price': trail['entry_price'],
                'current_price': trail['current_price'],
                'profit_pct': ((trail['entry_price'] - trail['current_price']) / trail['entry_price']) * 100,
                'is_activated': trail['is_activated'],
                'trailing_tp': trail['trailing_tp'],
                'max_profit_pct': trail['max_profit_pct'],
                'status': trail['status']
            })
        
        return {
            'active_count': len(active),
            'positions': active,
            'settings': {
                'activation_pct': self.activation_profit_pct,
                'trail_distance_pct': self.trail_distance_pct,
                'max_tracking_minutes': self.max_tracking_minutes
            }
        }
    
    def get_position_details(self, signal_id: str) -> Optional[Dict]:
        """Получить детали конкретной позиции."""
        return self.active_trails.get(signal_id)


# Глобальный экземпляр
_trailing_tracker = None

def get_trailing_tracker() -> TrailingTPTracker:
    global _trailing_tracker
    if _trailing_tracker is None:
        _trailing_tracker = TrailingTPTracker()
    return _trailing_tracker
