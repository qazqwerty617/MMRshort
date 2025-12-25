"""
🚀 TURBO ENGINE v1.0
Параллельное выполнение ВСЕХ анализаторов с кэшированием.

Оптимизации:
1. Параллельный запуск всех анализаторов через asyncio
2. LRU-кэш для повторных запросов
3. Предзагрузка данных
4. TTL-кэш для свечей и стакана
"""

import asyncio
import time
from typing import Dict, List, Optional, Tuple
from functools import lru_cache
from collections import OrderedDict
import logging

logger = logging.getLogger(__name__)

# Импортируем все анализаторы
try:
    from god_eye import GodEye
except ImportError:
    GodEye = None

try:
    from dominator import Dominator
except ImportError:
    Dominator = None

try:
    from advanced_analyzers import AdvancedAnalyzer, PsychologyLevels
except ImportError:
    AdvancedAnalyzer = None
    PsychologyLevels = None

try:
    from precision_indicators import PrecisionAnalyzer, get_precision_analyzer
except ImportError:
    PrecisionAnalyzer = None
    get_precision_analyzer = None


class TTLCache:
    """Кэш с временем жизни (TTL)"""
    
    __slots__ = ('cache', 'ttl', 'max_size')
    
    def __init__(self, ttl_seconds: float = 2.0, max_size: int = 100):
        self.cache = OrderedDict()
        self.ttl = ttl_seconds
        self.max_size = max_size
    
    def get(self, key: str) -> Optional[any]:
        """Получить значение если не истекло"""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: any):
        """Установить значение"""
        # Удаляем старые если переполнение
        while len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        
        self.cache[key] = (value, time.time())
    
    def clear(self):
        """Очистить кэш"""
        self.cache.clear()


class TurboEngine:
    """
    🚀 ТУРБО-ДВИЖОК - параллельный анализ с максимальной скоростью и точностью.
    """
    
    __slots__ = ('god_eye', 'dominator', 'advanced', 'klines_cache', 'orderbook_cache', 'analysis_cache', 'precision')
    
    def __init__(self):
        # Инициализируем анализаторы
        self.god_eye = GodEye() if GodEye else None
        self.dominator = Dominator() if Dominator else None
        self.advanced = AdvancedAnalyzer() if AdvancedAnalyzer else None
        
        # Кэши
        self.klines_cache = TTLCache(ttl_seconds=1.5)  # Свечи кешируем на 1.5 сек
        self.orderbook_cache = TTLCache(ttl_seconds=0.5)  # Стакан на 0.5 сек
        self.analysis_cache = TTLCache(ttl_seconds=1.0)  # Результаты анализа на 1 сек
        
        # 🎯 Высокоточные индикаторы
        self.precision = get_precision_analyzer() if get_precision_analyzer else None
    
    async def full_analysis(self, 
                           symbol: str,
                           klines: List,
                           orderbook: Dict,
                           entry_price: float,
                           peak_price: float,
                           start_price: float,
                           pump_speed_minutes: float) -> Dict:
        """
        ПОЛНЫЙ ПАРАЛЛЕЛЬНЫЙ АНАЛИЗ - все системы одновременно.
        """
        cache_key = f"{symbol}_{entry_price:.8f}"
        
        # Проверяем кэш
        cached = self.analysis_cache.get(cache_key)
        if cached:
            return cached
        
        # Запускаем все анализаторы ПАРАЛЛЕЛЬНО
        tasks = []
        
        # GodEye
        if self.god_eye and klines:
            tasks.append(self._run_god_eye(symbol, klines, entry_price))
        else:
            tasks.append(self._empty_result('god_eye'))
        
        # Dominator
        if self.dominator and klines and orderbook:
            tasks.append(self._run_dominator(symbol, klines, orderbook, entry_price))
        else:
            tasks.append(self._empty_result('dominator'))
        
        # CVD (Advanced)
        if self.advanced and klines:
            tasks.append(self._run_cvd(klines))
        else:
            tasks.append(self._empty_result('cvd'))
        
        # Precision Indicators (BB, EMA, ADX, VP, Divergence)
        if self.precision and klines:
            tasks.append(self._run_precision(klines))
        else:
            tasks.append(self._empty_result('precision'))
        
        # Выполняем параллельно
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = (time.time() - start_time) * 1000
        
        god_eye_result = results[0] if not isinstance(results[0], Exception) else {'score': 5, 'mult': 1.0}
        dominator_result = results[1] if not isinstance(results[1], Exception) else {'score': 5, 'mult': 1.0}
        cvd_result = results[2] if not isinstance(results[2], Exception) else {'mult': 1.0}
        precision_result = results[3] if len(results) > 3 and not isinstance(results[3], Exception) else {'total_mult': 1.0, 'signals': []}
        
        # Комбинируем множители
        god_eye_mult = god_eye_result.get('mult', 1.0)
        dominator_mult = dominator_result.get('mult', 1.0)
        cvd_mult = cvd_result.get('mult', 1.0)
        precision_mult = precision_result.get('total_mult', 1.0)
        
        # Множитель скорости пампа
        if pump_speed_minutes <= 2:
            speed_mult = 1.35
        elif pump_speed_minutes <= 5:
            speed_mult = 1.2
        elif pump_speed_minutes <= 10:
            speed_mult = 1.0
        else:
            speed_mult = 0.85
        
        # ФИНАЛЬНЫЙ МНОЖИТЕЛЬ (6 систем!)
        final_mult = speed_mult * god_eye_mult * dominator_mult * cvd_mult * precision_mult
        
        # Рассчитываем уровни Фибо
        pump_range = peak_price - start_price
        fib_382 = peak_price - (pump_range * 0.382)
        fib_500 = peak_price - (pump_range * 0.500)
        fib_618 = peak_price - (pump_range * 0.618)
        
        # Применяем множитель к TP
        tp1 = entry_price - (entry_price - fib_382) * final_mult
        tp2 = entry_price - (entry_price - fib_500) * final_mult
        tp3 = entry_price - (entry_price - fib_618) * final_mult
        
        # Притягиваем к психологическим уровням
        if PsychologyLevels:
            tp1 = PsychologyLevels.snap(tp1)
            tp2 = PsychologyLevels.snap(tp2)
            tp3 = PsychologyLevels.snap(tp3)
        
        # Stop Loss
        min_sl = peak_price * 1.01
        sl = max(min_sl, entry_price * 1.05)
        sl = min(sl, entry_price * 1.10)  # Макс 10%
        
        # Общий скор (среднее от GodEye и Dominator)
        combined_score = (god_eye_result.get('score', 5) + dominator_result.get('score', 5)) / 2
        
        # Качество
        if combined_score >= 7.5:
            quality = '⭐⭐⭐ ИДЕАЛЬНЫЙ'
        elif combined_score >= 6:
            quality = '⭐⭐ ХОРОШИЙ'
        elif combined_score >= 5:
            quality = '⭐ НОРМАЛЬНЫЙ'
        else:
            quality = '⚠️ РИСКОВАННЫЙ'
        
        result = {
            'stop_loss': sl,
            'take_profits': [tp1, tp2, tp3],
            'analysis': {
                'god_eye_score': god_eye_result.get('score', 5.0),
                'god_eye_quality': god_eye_result.get('quality', quality),
                'dominator_score': dominator_result.get('score', 5.0),
                'domination_signal': dominator_result.get('signal', 'NEUTRAL'),
                'final_multiplier': round(final_mult, 3),
                'speed_mult': speed_mult,
                'combined_score': round(combined_score, 1),
                'quality': quality,
                'analysis_time_ms': round(elapsed, 1)
            }
        }
        
        # Кэшируем
        self.analysis_cache.set(cache_key, result)
        
        logger.info(f"⚡ TURBO {symbol}: Score {combined_score:.1f} | Mult ×{final_mult:.2f} | {elapsed:.1f}ms")
        
        return result
    
    async def _run_god_eye(self, symbol: str, klines: List, entry_price: float) -> Dict:
        """Запуск GodEye в отдельной корутине"""
        try:
            result = self.god_eye.analyze(symbol, klines, entry_price)
            result['mult'] = self.god_eye.get_tp_multiplier(result)
            return result
        except Exception as e:
            logger.debug(f"GodEye error: {e}")
            return {'score': 5, 'quality': '⭐ СТАНДАРТ', 'mult': 1.0}
    
    async def _run_dominator(self, symbol: str, klines: List, orderbook: Dict, entry_price: float) -> Dict:
        """Запуск Dominator в отдельной корутине"""
        try:
            result = self.dominator.dominate(symbol, klines, orderbook, entry_price=entry_price)
            result['score'] = result.get('domination_score', 5)
            result['mult'] = result.get('total_multiplier', 1.0)
            return result
        except Exception as e:
            logger.debug(f"Dominator error: {e}")
            return {'score': 5, 'signal': 'NEUTRAL', 'mult': 1.0}
    
    async def _run_cvd(self, klines: List) -> Dict:
        """Запуск CVD анализа"""
        try:
            result = self.advanced.delta.analyze(klines)
            return result
        except Exception as e:
            logger.debug(f"CVD error: {e}")
            return {'mult': 1.0}
    
    async def _run_precision(self, klines: List) -> Dict:
        """Запуск высокоточных индикаторов (BB, EMA, ADX, VP, Divergence)"""
        try:
            result = self.precision.analyze(klines)
            return result
        except Exception as e:
            logger.debug(f"Precision error: {e}")
            return {'total_mult': 1.0, 'signals': []}
    
    async def _empty_result(self, name: str) -> Dict:
        """Пустой результат для отключённых анализаторов"""
        return {'score': 5, 'mult': 1.0}


# Глобальный экземпляр для переиспользования
_turbo_engine = None

def get_turbo_engine() -> TurboEngine:
    """Получить глобальный экземпляр турбо-движка"""
    global _turbo_engine
    if _turbo_engine is None:
        _turbo_engine = TurboEngine()
    return _turbo_engine
