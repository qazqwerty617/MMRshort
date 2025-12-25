"""
🔮 GOD EYE - TURBO EDITION v2.0
Оптимизировано для МАКСИМАЛЬНОЙ СКОРОСТИ.

Оптимизации:
- __slots__ для экономии памяти
- Упрощённые расчёты RSI/MACD
- Минимум итераций
- Быстрые множители
"""

import math
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MarketRegimeFast:
    """Режим рынка - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def detect(klines: List) -> Dict:
        """Быстрое определение режима"""
        if not klines or len(klines) < 10:
            return {'regime': 'unknown', 'mult': 1.0}
        
        # Берём последние 10 свечей для скорости
        closes = [float(k[4]) for k in klines[-10:]]
        
        price_change = (closes[-1] - closes[0]) / closes[0] * 100
        
        # Волатильность (упрощённо)
        avg_price = sum(closes) / len(closes)
        volatility = sum(abs(c - avg_price) for c in closes) / len(closes) / avg_price * 100
        
        if volatility > 5:
            regime = 'VOLATILE'
            mult = 1.15
        elif price_change > 3:
            regime = 'BULLISH'
            mult = 0.9  # Осторожнее с шортами
        elif price_change < -3:
            regime = 'BEARISH'
            mult = 1.15  # Усиливаем шорты
        else:
            regime = 'RANGING'
            mult = 1.0
        
        return {'regime': regime, 'change': round(price_change, 1), 'mult': mult}


class MomentumFast:
    """Моментум - TURBO версия (RSI + простой тренд)"""
    
    __slots__ = ()
    
    @staticmethod
    def analyze(klines: List) -> Dict:
        """Быстрый анализ моментума"""
        if not klines or len(klines) < 15:
            return {'rsi': 50, 'trend': 'neutral', 'mult': 1.0}
        
        closes = [float(k[4]) for k in klines[-15:]]
        
        # Упрощённый RSI
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
            else:
                losses.append(abs(change))
        
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0.001
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        # Множитель
        if rsi > 75:
            mult = 1.2  # Очень перекуплен
            trend = 'overbought'
        elif rsi > 60:
            mult = 1.1
            trend = 'bullish'
        elif rsi < 25:
            mult = 0.85  # Перепродан
            trend = 'oversold'
        else:
            mult = 1.0
            trend = 'neutral'
        
        return {'rsi': round(rsi, 1), 'trend': trend, 'mult': mult}


class VWAPFast:
    """VWAP - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def analyze(klines: List) -> Dict:
        """Быстрый VWAP"""
        if not klines or len(klines) < 5:
            return {'deviation': 0, 'mult': 1.0}
        
        tp_vol = 0
        total_vol = 0
        
        for k in klines[-20:]:
            tp = (float(k[2]) + float(k[3]) + float(k[4])) / 3
            vol = float(k[5])
            tp_vol += tp * vol
            total_vol += vol
        
        if total_vol == 0:
            return {'deviation': 0, 'mult': 1.0}
        
        vwap = tp_vol / total_vol
        current = float(klines[-1][4])
        deviation = (current - vwap) / vwap * 100
        
        # Множитель
        if deviation > 5:
            mult = 1.15  # Цена сильно выше VWAP
        elif deviation > 2:
            mult = 1.05
        elif deviation < -5:
            mult = 0.9  # Цена сильно ниже VWAP
        else:
            mult = 1.0
        
        return {'deviation': round(deviation, 1), 'mult': mult}


class PatternFast:
    """Паттерны - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def detect(klines: List) -> Dict:
        """Быстрое обнаружение паттернов разворота"""
        if not klines or len(klines) < 3:
            return {'pattern': None, 'mult': 1.0}
        
        last = klines[-1]
        open_p = float(last[1])
        high = float(last[2])
        low = float(last[3])
        close = float(last[4])
        
        body = abs(close - open_p)
        total = high - low
        
        if total == 0:
            return {'pattern': None, 'mult': 1.0}
        
        upper_wick = high - max(open_p, close)
        upper_ratio = upper_wick / total
        body_ratio = body / total
        
        # Shooting Star (падающая звезда) - отличный сигнал для шорта
        if upper_ratio > 0.6 and body_ratio < 0.3:
            return {'pattern': 'SHOOTING_STAR', 'mult': 1.25}
        
        # Bearish Engulfing (упрощённо)
        if len(klines) >= 2:
            prev_close = float(klines[-2][4])
            prev_open = float(klines[-2][1])
            if close < open_p and prev_close > prev_open:  # Красная после зелёной
                if close < prev_open and open_p > prev_close:
                    return {'pattern': 'BEARISH_ENGULFING', 'mult': 1.2}
        
        # Длинная верхняя тень
        if upper_ratio > 0.5:
            return {'pattern': 'LONG_UPPER_WICK', 'mult': 1.1}
        
        return {'pattern': None, 'mult': 1.0}


class SessionFast:
    """Торговые сессии - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def analyze() -> Dict:
        """Быстрый анализ сессии"""
        hour = datetime.now(timezone.utc).hour
        
        # Overlap Europe/America (13-16 UTC) = максимум волатильности
        if 13 <= hour < 16:
            return {'session': 'OVERLAP', 'mult': 1.15}
        # America (13-22 UTC)
        elif 13 <= hour < 22:
            return {'session': 'AMERICA', 'mult': 1.1}
        # Europe (7-16 UTC)
        elif 7 <= hour < 16:
            return {'session': 'EUROPE', 'mult': 1.05}
        # Asia (0-8 UTC)
        elif 0 <= hour < 8:
            return {'session': 'ASIA', 'mult': 1.0}
        # Dead hours
        else:
            return {'session': 'OFF', 'mult': 0.9}


class GodEyeTurbo:
    """
    🔮 GOD EYE TURBO - Максимально быстрая версия.
    Все анализаторы оптимизированы.
    """
    
    __slots__ = ('regime', 'momentum', 'vwap', 'patterns', 'session')
    
    def __init__(self):
        self.regime = MarketRegimeFast()
        self.momentum = MomentumFast()
        self.vwap = VWAPFast()
        self.patterns = PatternFast()
        self.session = SessionFast()
    
    def analyze(self, symbol: str, klines: List, entry_price: float = None) -> Dict:
        """
        ТУРБО-АНАЛИЗ - все расчёты оптимизированы.
        """
        if not klines:
            return {'score': 5, 'signal': 'NEUTRAL', 'confidence': 0.5}
        
        total_mult = 1.0
        details = {}
        
        # 1. Режим рынка
        regime = self.regime.detect(klines)
        total_mult *= regime['mult']
        details['regime'] = regime['regime']
        
        # 2. Моментум (RSI)
        momentum = self.momentum.analyze(klines)
        total_mult *= momentum['mult']
        details['rsi'] = momentum['rsi']
        
        # 3. VWAP
        vwap = self.vwap.analyze(klines)
        total_mult *= vwap['mult']
        details['vwap_dev'] = vwap['deviation']
        
        # 4. Паттерны
        pattern = self.patterns.detect(klines)
        total_mult *= pattern['mult']
        details['pattern'] = pattern['pattern']
        
        # 5. Сессия
        session = self.session.analyze()
        total_mult *= session['mult']
        details['session'] = session['session']
        
        # Финальный скор
        score = min(10, max(1, 5.0 * total_mult))
        
        # Quality
        if score >= 8:
            quality = '⭐⭐⭐ ИДЕАЛЬНЫЙ'
        elif score >= 6.5:
            quality = '⭐⭐ ХОРОШИЙ'
        elif score >= 5:
            quality = '⭐ НОРМАЛЬНЫЙ'
        else:
            quality = '⚠️ РИСКОВАННЫЙ'
        
        # Signal
        if score >= 7:
            signal = 'STRONG_SHORT'
        elif score >= 5.5:
            signal = 'SHORT'
        else:
            signal = 'NEUTRAL'
        
        return {
            'score': round(score, 1),
            'signal': signal,
            'quality': quality,
            'confidence': min(1.0, 0.5 + (score - 5) * 0.1),
            'details': details
        }
    
    def get_tp_multiplier(self, analysis: Dict) -> float:
        """Множитель для TP"""
        score = analysis.get('score', 5)
        return 1.0 + (score - 5) * 0.03
    
    def get_entry_quality(self, analysis: Dict) -> str:
        """Качество входа"""
        return analysis.get('quality', '⭐ СТАНДАРТ')


# Алиас для обратной совместимости
GodEye = GodEyeTurbo
