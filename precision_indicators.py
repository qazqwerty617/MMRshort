"""
🎯 PRECISION INDICATORS v1.0
Высокоточные индикаторы для максимальной точности сигналов.

Индикаторы:
1. Bollinger Bands - волатильность и перекупленность
2. EMA Crossover - подтверждение тренда (9/21)
3. ADX - сила тренда
4. Volume Profile - POC (точка контроля)
5. Multi-Timeframe Confirmation - подтверждение на старшем ТФ
6. Momentum Divergence - дивергенции моментума
"""

import math
import logging
from typing import Dict, List, Tuple, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)


class BollingerBands:
    """
    Bollinger Bands - определение волатильности и экстремумов.
    Цена выше верхней полосы = перекуплено (хорошо для шорта)
    """
    
    __slots__ = ()
    
    @staticmethod
    def calculate(closes: List[float], period: int = 20, std_dev: float = 2.0) -> Dict:
        """Рассчитать Bollinger Bands"""
        if len(closes) < period:
            return {'position': 'middle', 'squeeze': False, 'mult': 1.0}
        
        # SMA
        sma = sum(closes[-period:]) / period
        
        # Standard Deviation
        variance = sum((c - sma) ** 2 for c in closes[-period:]) / period
        std = math.sqrt(variance)
        
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        current = closes[-1]
        
        # Bandwidth (сжатие)
        bandwidth = (upper - lower) / sma * 100 if sma > 0 else 0
        squeeze = bandwidth < 4  # Сжатие = низкая волатильность
        
        # Позиция цены
        if current > upper:
            position = 'above_upper'  # Перекуплено - ОТЛИЧНО для шорта
            mult = 1.25
        elif current > sma + std:
            position = 'high'
            mult = 1.15
        elif current < lower:
            position = 'below_lower'  # Перепродано
            mult = 0.85
        else:
            position = 'middle'
            mult = 1.0
        
        # Бонус за сжатие перед движением
        if squeeze and position in ['above_upper', 'high']:
            mult *= 1.1  # Сжатие + перекупленность = сильный сигнал
        
        return {
            'position': position,
            'squeeze': squeeze,
            'bandwidth': round(bandwidth, 2),
            'upper': round(upper, 8),
            'lower': round(lower, 8),
            'sma': round(sma, 8),
            'mult': mult
        }


class EMACrossover:
    """
    EMA Crossover (9/21) - подтверждение тренда.
    Быстрая EMA ниже медленной = медвежий тренд
    """
    
    __slots__ = ()
    
    @staticmethod
    def calculate(closes: List[float], fast: int = 9, slow: int = 21) -> Dict:
        """Рассчитать EMA кроссовер"""
        if len(closes) < slow + 5:
            return {'trend': 'neutral', 'crossover': 'none', 'mult': 1.0}
        
        def ema(data: List[float], period: int) -> float:
            """Рассчитать последнее значение EMA"""
            multiplier = 2 / (period + 1)
            ema_val = sum(data[:period]) / period
            for price in data[period:]:
                ema_val = (price - ema_val) * multiplier + ema_val
            return ema_val
        
        # Текущие EMA
        ema_fast = ema(closes, fast)
        ema_slow = ema(closes, slow)
        
        # Предыдущие EMA (для определения кроссовера)
        ema_fast_prev = ema(closes[:-1], fast)
        ema_slow_prev = ema(closes[:-1], slow)
        
        # Определяем тренд
        if ema_fast < ema_slow:
            trend = 'bearish'
            mult = 1.15
        elif ema_fast > ema_slow:
            trend = 'bullish'
            mult = 0.9
        else:
            trend = 'neutral'
            mult = 1.0
        
        # Кроссовер
        crossover = 'none'
        if ema_fast_prev >= ema_slow_prev and ema_fast < ema_slow:
            crossover = 'bearish'  # Только что пересекли вниз
            mult *= 1.15
        elif ema_fast_prev <= ema_slow_prev and ema_fast > ema_slow:
            crossover = 'bullish'
            mult *= 0.85
        
        return {
            'trend': trend,
            'crossover': crossover,
            'ema_fast': round(ema_fast, 8),
            'ema_slow': round(ema_slow, 8),
            'mult': mult
        }


class ADXIndicator:
    """
    ADX (Average Directional Index) - сила тренда.
    ADX > 25 = сильный тренд, ADX < 20 = слабый/боковик
    """
    
    __slots__ = ()
    
    @staticmethod
    def calculate(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict:
        """Рассчитать ADX"""
        if len(closes) < period + 5:
            return {'adx': 25, 'trend_strength': 'medium', 'mult': 1.0}
        
        # Упрощённый расчёт ADX
        tr_list = []
        plus_dm_list = []
        minus_dm_list = []
        
        for i in range(1, len(closes)):
            high = highs[i]
            low = lows[i]
            prev_high = highs[i-1]
            prev_low = lows[i-1]
            prev_close = closes[i-1]
            
            # True Range
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
            
            # Directional Movement
            plus_dm = high - prev_high if high - prev_high > prev_low - low else 0
            minus_dm = prev_low - low if prev_low - low > high - prev_high else 0
            plus_dm_list.append(max(plus_dm, 0))
            minus_dm_list.append(max(minus_dm, 0))
        
        if len(tr_list) < period:
            return {'adx': 25, 'trend_strength': 'medium', 'mult': 1.0}
        
        # Средние значения
        atr = sum(tr_list[-period:]) / period
        plus_di = sum(plus_dm_list[-period:]) / atr * 100 if atr > 0 else 0
        minus_di = sum(minus_dm_list[-period:]) / atr * 100 if atr > 0 else 0
        
        # DX
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
        
        # ADX (упрощённо = DX)
        adx = dx
        
        # Множитель
        if adx > 40:
            trend_strength = 'very_strong'
            mult = 1.2  # Сильный тренд = уверенно шортим
        elif adx > 25:
            trend_strength = 'strong'
            mult = 1.1
        elif adx < 20:
            trend_strength = 'weak'
            mult = 0.9  # Слабый тренд = осторожнее
        else:
            trend_strength = 'medium'
            mult = 1.0
        
        # Направление
        direction = 'down' if minus_di > plus_di else 'up'
        
        # Бонус если тренд вниз и сильный
        if direction == 'down' and trend_strength in ['strong', 'very_strong']:
            mult *= 1.1
        
        return {
            'adx': round(adx, 1),
            'trend_strength': trend_strength,
            'direction': direction,
            'plus_di': round(plus_di, 1),
            'minus_di': round(minus_di, 1),
            'mult': mult
        }


class VolumeProfile:
    """
    Volume Profile - определение POC (Point of Control).
    POC = уровень с максимальным объёмом, сильный магнит для цены.
    """
    
    __slots__ = ()
    
    @staticmethod
    def calculate(klines: List, num_levels: int = 20) -> Dict:
        """Найти POC и Value Area"""
        if not klines or len(klines) < 10:
            return {'poc': None, 'mult': 1.0}
        
        # Собираем объём по ценовым уровням
        price_volume = {}
        
        for k in klines:
            high = float(k[2])
            low = float(k[3])
            close = float(k[4])
            volume = float(k[5])
            
            # Типичная цена
            tp = (high + low + close) / 3
            
            # Округляем до уровня
            level = round(tp, 6)
            price_volume[level] = price_volume.get(level, 0) + volume
        
        if not price_volume:
            return {'poc': None, 'mult': 1.0}
        
        # POC = уровень с максимальным объёмом
        poc_level = max(price_volume, key=price_volume.get)
        poc_volume = price_volume[poc_level]
        
        current_price = float(klines[-1][4])
        
        # Если цена выше POC - хорошо для шорта (будет тянуть вниз)
        if current_price > poc_level * 1.02:
            mult = 1.15
            position = 'above_poc'
        elif current_price < poc_level * 0.98:
            mult = 0.9
            position = 'below_poc'
        else:
            mult = 1.0
            position = 'at_poc'
        
        return {
            'poc': poc_level,
            'poc_volume': poc_volume,
            'position': position,
            'mult': mult
        }


class MomentumDivergence:
    """
    Дивергенция моментума - цена↑ но моментум↓ = разворот.
    Очень точный сигнал для шорта.
    """
    
    __slots__ = ()
    
    @staticmethod
    def detect(closes: List[float], period: int = 10) -> Dict:
        """Обнаружить дивергенцию"""
        if len(closes) < period + 5:
            return {'divergence': False, 'type': 'none', 'mult': 1.0}
        
        # Простой моментум = Rate of Change
        price_change = (closes[-1] - closes[-period]) / closes[-period] * 100
        
        # Моментум средней скорости движения
        mid = len(closes) // 2
        first_half_change = (closes[mid] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
        second_half_change = (closes[-1] - closes[mid]) / closes[mid] * 100 if closes[mid] > 0 else 0
        
        # Bearish divergence: цена растёт (или на хаях), но скорость падает
        if price_change > 0 and second_half_change < first_half_change * 0.5:
            return {
                'divergence': True,
                'type': 'bearish',
                'price_change': round(price_change, 2),
                'momentum_slowdown': True,
                'mult': 1.25  # Сильный сигнал для шорта!
            }
        
        # Bullish divergence (плохо для шорта)
        if price_change < 0 and second_half_change > first_half_change:
            return {
                'divergence': True,
                'type': 'bullish',
                'mult': 0.85
            }
        
        return {'divergence': False, 'type': 'none', 'mult': 1.0}


class PrecisionAnalyzer:
    """
    🎯 Объединяет все высокоточные индикаторы.
    """
    
    __slots__ = ('bb', 'ema', 'adx', 'vp', 'divergence')
    
    def __init__(self):
        self.bb = BollingerBands()
        self.ema = EMACrossover()
        self.adx = ADXIndicator()
        self.vp = VolumeProfile()
        self.divergence = MomentumDivergence()
    
    def analyze(self, klines: List) -> Dict:
        """Полный точный анализ"""
        if not klines or len(klines) < 25:
            return {'precision_score': 5, 'mult': 1.0, 'signals': []}
        
        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        
        signals = []
        total_mult = 1.0
        
        # 1. Bollinger Bands
        bb = self.bb.calculate(closes)
        total_mult *= bb['mult']
        if bb['position'] == 'above_upper':
            signals.append("📈 BB: Выше верхней полосы (перекуплен)")
        
        # 2. EMA Crossover
        ema = self.ema.calculate(closes)
        total_mult *= ema['mult']
        if ema['crossover'] == 'bearish':
            signals.append("📉 EMA: Медвежий кроссовер 9/21")
        elif ema['trend'] == 'bearish':
            signals.append("📉 EMA: Медвежий тренд")
        
        # 3. ADX
        adx = self.adx.calculate(highs, lows, closes)
        total_mult *= adx['mult']
        if adx['direction'] == 'down' and adx['trend_strength'] in ['strong', 'very_strong']:
            signals.append(f"💪 ADX: Сильный нисходящий тренд ({adx['adx']:.0f})")
        
        # 4. Volume Profile
        vp = self.vp.calculate(klines)
        total_mult *= vp['mult']
        if vp['position'] == 'above_poc':
            signals.append("📊 VP: Цена выше POC")
        
        # 5. Momentum Divergence
        div = self.divergence.detect(closes)
        total_mult *= div['mult']
        if div['divergence'] and div['type'] == 'bearish':
            signals.append("⚠️ ДИВЕРГЕНЦИЯ: Моментум слабеет!")
        
        # Precision Score
        base_score = 5.0
        score = min(10, max(1, base_score * total_mult))
        
        return {
            'precision_score': round(score, 1),
            'total_mult': round(total_mult, 3),
            'signals': signals,
            'details': {
                'bb': bb,
                'ema': ema,
                'adx': adx,
                'vp': vp,
                'divergence': div
            }
        }


# Глобальный экземпляр
_precision = None

def get_precision_analyzer() -> PrecisionAnalyzer:
    global _precision
    if _precision is None:
        _precision = PrecisionAnalyzer()
    return _precision
