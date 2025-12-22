"""
Pump Detector - обнаружение аномальных пампов
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
from logger import get_logger

logger = get_logger()


class PumpDetector:
    """Класс для обнаружения пампов"""
    
    def __init__(self, config: Dict):
        """
        Инициализация детектора
        
        Args:
            config: Конфигурация из config.yaml секции 'pump_detection'
        """
        self.config = config
        self.min_increase = config['min_price_increase_pct']
        self.max_increase = config['max_price_increase_pct']
        self.timeframe = config['timeframe_minutes']
        self.min_volume_spike = config['min_volume_spike']
        self.min_volume_usd = config['min_volume_usd']
        
        # Хранилище данных по монетам
        self.price_history: Dict[str, List[Dict]] = {}
        self.volume_history: Dict[str, List[float]] = {}
    
    def add_price_data(self, symbol: str, price: float, volume: float, timestamp: int):
        """
        Добавить данные о цене
        
        Args:
            symbol: Символ пары
            price: Цена
            volume: Объём
            timestamp: Timestamp в миллисекундах
        """
        if symbol not in self.price_history:
            self.price_history[symbol] = []
            self.volume_history[symbol] = []
        
        self.price_history[symbol].append({
            "price": price,
            "volume": volume,
            "timestamp": timestamp
        })
        
        # Удаляем старые данные (старше timeframe * 2)
        cutoff_time = timestamp - (self.timeframe * 2 * 60 * 1000)
        self.price_history[symbol] = [
            d for d in self.price_history[symbol] 
            if d["timestamp"] > cutoff_time
        ]
    
    def detect_pump(self, symbol: str) -> Optional[Dict]:
        """Проверить наличие пампа"""
        # ВРЕМЕННО: Агрессивное логирование первых 10 символов
        debug_symbols = ['BTC_USDT', 'ETH_USDT', 'BNB_USDT', 'SOL_USDT', 'XRP_USDT',
                        'DOGE_USDT', 'ADA_USDT', 'MATIC_USDT', 'DOT_USDT', 'LINK_USDT']
        is_debug = symbol in debug_symbols
        
        # 🔥 DIAGNOSTIC: Log data accumulation for EVERY 100th call
        import random
        if random.random() < 0.001:  # 0.1% chance to log
            count = len(self.price_history.get(symbol, []))
            logger.warning(f"🔬 DIAG {symbol}: {count} точек данных")
        
        if symbol not in self.price_history or len(self.price_history[symbol]) < 3:
            if is_debug:
                count = len(self.price_history.get(symbol, []))
                logger.warning(f"⏭️ SKIP {symbol}: Недостаточно данных ({count} точек)")
            return None
        
        data = self.price_history[symbol]
        current_time = data[-1]["timestamp"]
        timeframe_ms = self.timeframe * 60 * 1000
        
        # Получаем данные за последний timeframe
        recent_data = [d for d in data if d["timestamp"] >= current_time - timeframe_ms]
        
        if len(recent_data) < 2:
            if is_debug:
                logger.info(f"⏭️ SKIP {symbol}: Мало данных ({len(recent_data)} за {self.timeframe}мин)")
            return None
        
        # Находим начальную и пиковую цену
        price_start = recent_data[0]["price"]
        price_peak = max(d["price"] for d in recent_data)
        current_price = recent_data[-1]["price"]
        
        if price_start == 0 or price_start is None:
            return None
        
        # Рассчитываем рост
        price_increase_pct = ((price_peak - price_start) / price_start) * 100
        
        # 🔥 СУПЕР-ДИАГНОСТИКА: Логируем КАЖДЫЙ расчёт (с вероятностью 0.5%)
        if random.random() < 0.005:  # 0.5% шанс
            logger.warning(f"🔬 CALC {symbol}: Рост={price_increase_pct:.2f}% | "
                          f"{price_start:.8f}→{price_peak:.8f} | {len(recent_data)} точек")
        
        # 🔥 АГРЕССИВНОЕ ЛОГИРОВАНИЕ: Логируем ВСЕ монеты с ростом >= 2%
        if price_increase_pct >= 2.0:
            logger.warning(f"📊 {symbol}: Рост={price_increase_pct:.1f}% за {self.timeframe}мин | "
                          f"Цена: {price_start:.6f}→{price_peak:.6f} | Точек={len(recent_data)}")
        elif is_debug:
            # Для debug символов логируем даже маленькие движения
            logger.info(f"📊 {symbol}: Рост={price_increase_pct:.3f}% (мин={self.min_increase}%)")

        # Проверяем условия пампа
        if not (self.min_increase <= price_increase_pct <= self.max_increase):
            # Логируем отклонённые пампы с ростом >= 5%
            if price_increase_pct >= 5.0:
                logger.warning(f"⚠️ {symbol}: Рост +{price_increase_pct:.1f}% НЕ прошёл (нужно {self.min_increase}%-{self.max_increase}%)")
            return None
        
        # Проверяем всплеск объёма
        avg_volume = self._calculate_avg_volume(symbol, current_time, timeframe_ms * 3)
        
        if avg_volume == 0:
            if is_debug:
                logger.info(f"⚠️ {symbol}: Средний объем = 0")
            return None
        
        recent_volume = sum(d["volume"] for d in recent_data)
        volume_spike = recent_volume / avg_volume if avg_volume > 0 else 0
        
        if is_debug:
            logger.warning(f"💹 {symbol}: Volume spike={volume_spike:.2f}x (мин={self.min_volume_spike}x), avg={avg_volume:.2f}, recent={recent_volume:.2f}")
        
        if volume_spike < self.min_volume_spike:
            if is_debug or price_increase_pct >= 10.0:  # Логируем сильные движения
                logger.warning(f"❌ {symbol}: Рост +{price_increase_pct:.1f}%, но всплеск объёма {volume_spike:.2f} < {self.min_volume_spike}")
            return None
        
        # Проверяем минимальный объём в USD
        if len(recent_data) == 0:
            return None
            
        avg_price = sum(d["price"] for d in recent_data) / len(recent_data)
        volume_usd = recent_volume * avg_price
        
        if is_debug:
            logger.info(f"💰 {symbol}: Volume USD={volume_usd:.0f} (мин={self.min_volume_usd})")
        
        if volume_usd < self.min_volume_usd:
            if is_debug or price_increase_pct >= 10.0:
                 logger.warning(f"❌ {symbol}: Рост +{price_increase_pct:.1f}%, но объём ${volume_usd:.0f} < ${self.min_volume_usd}")
            return None
        
        # Памп обнаружен!
        logger.warning(f"🚀 ПАМП ОБНАРУЖЕН: {symbol} +{price_increase_pct:.1f}% за {self.timeframe}мин (объём x{volume_spike:.1f})")
        
        return {
            "symbol": symbol,
            "price_start": price_start,
            "price_peak": price_peak,
            "current_price": current_price,
            "increase_pct": price_increase_pct,
            "volume_spike": volume_spike,
            "volume_usd": volume_usd,
            "detected_at": datetime.now(),
            "timeframe_minutes": self.timeframe
        }
    
    def _calculate_avg_volume(self, symbol: str, current_time: int, lookback_ms: int) -> float:
        """Рассчитать средний объём за период"""
        if symbol not in self.price_history:
            return 0.0
        
        cutoff = current_time - lookback_ms - (self.timeframe * 60 * 1000)
        historical_data = [
            d for d in self.price_history[symbol]
            if d["timestamp"] < current_time - (self.timeframe * 60 * 1000)
            and d["timestamp"] >= cutoff
        ]
        
        if not historical_data:
            # Fallback: используем текущие данные
            return sum(d["volume"] for d in self.price_history[symbol]) / len(self.price_history[symbol])
        
        total_volume = sum(d["volume"] for d in historical_data)
        return total_volume / len(historical_data) if historical_data else 0.0
    
    def get_price_history(self, symbol: str) -> List[float]:
        """Получить историю цен"""
        if symbol not in self.price_history:
            return []
        return [d["price"] for d in self.price_history[symbol]]
    
    def get_volume_history(self, symbol: str) -> List[float]:
        """Получить историю объёмов"""
        if symbol not in self.price_history:
            return []
        return [d["volume"] for d in self.price_history[symbol]]
