"""
Advanced Market Analyzers - TURBO EDITION v2.0
Оптимизировано для МАКСИМАЛЬНОЙ СКОРОСТИ.

Оптимизации:
- __slots__ для экономии памяти
- Минимум итераций
- Упрощённые расчёты
- Быстрые множители
"""

import math
import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class DeltaVolumeFast:
    """CVD - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def analyze(klines: List) -> Dict:
        """Быстрый анализ CVD"""
        if not klines or len(klines) < 5:
            return {'cvd': 0, 'mult': 1.0}
        
        cvd = 0
        for k in klines[-10:]:
            open_p = float(k[1])
            close = float(k[4])
            volume = float(k[5])
            
            # Простая логика: зелёная = +vol, красная = -vol
            if close > open_p:
                cvd += volume
            else:
                cvd -= volume
        
        # Определяем дивергенцию
        price_change = float(klines[-1][4]) - float(klines[0][4])
        
        # Цена растёт, но CVD падает = дивергенция (хорошо для шорта)
        divergence = price_change > 0 and cvd < 0
        
        if divergence:
            mult = 1.2
        elif cvd < 0:
            mult = 1.1
        elif cvd > 0:
            mult = 0.95
        else:
            mult = 1.0
        
        return {'cvd': round(cvd, 2), 'divergence': divergence, 'mult': mult}
    
    @staticmethod
    def get_tp_multiplier(analysis: Dict) -> float:
        return analysis.get('mult', 1.0)


class TradeFlowFast:
    """Trade Flow - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def analyze(trades: List, current_price: float) -> Dict:
        """Быстрый анализ потока сделок"""
        if not trades:
            return {'sell_pressure': 0.5, 'mult': 1.0}
        
        sell_vol = 0
        buy_vol = 0
        
        for t in trades[-50:]:  # Последние 50 сделок
            vol = float(t.get('qty', 0)) * float(t.get('price', current_price))
            if t.get('side') == 'sell':
                sell_vol += vol
            else:
                buy_vol += vol
        
        total = sell_vol + buy_vol
        if total == 0:
            return {'sell_pressure': 0.5, 'mult': 1.0}
        
        sell_pressure = sell_vol / total
        
        if sell_pressure > 0.7:
            mult = 1.15
        elif sell_pressure > 0.6:
            mult = 1.05
        elif sell_pressure < 0.3:
            mult = 0.9
        else:
            mult = 1.0
        
        return {'sell_pressure': round(sell_pressure, 2), 'mult': mult}


class LiquidationFast:
    """Liquidation Levels - TURBO версия"""
    
    __slots__ = ()
    LEVERAGES = [10, 20, 50]  # Только важные
    
    @staticmethod
    def calculate(entry_price: float, peak_price: float) -> List[float]:
        """Быстрый расчёт уровней ликвидации"""
        levels = []
        for lev in LiquidationFast.LEVERAGES:
            liq = peak_price * (1 - 0.9 / lev)
            if liq < entry_price:
                levels.append(round(liq, 8))
        return levels


class PsychologyFast:
    """Psychology Levels - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def snap(price: float, within_pct: float = 1.0) -> float:
        """Быстрое притягивание к круглому числу"""
        if price <= 0:
            return price
        
        # Определяем порядок
        if price >= 1:
            step = 10 ** (len(str(int(price))) - 2)
        else:
            # Для мелких цен
            decimal_places = abs(int(math.log10(price))) + 1
            step = 10 ** (-decimal_places)
        
        if step == 0:
            return price
        
        rounded = round(price / step) * step
        
        # Проверяем, достаточно ли близко
        if abs(rounded - price) / price <= within_pct / 100:
            return rounded
        
        return price


class AdvancedAnalyzerTurbo:
    """Объединяет все TURBO-анализаторы"""
    
    __slots__ = ('delta', 'flow', 'liquidation', 'psychology')
    
    def __init__(self):
        self.delta = DeltaVolumeFast()
        self.flow = TradeFlowFast()
        self.liquidation = LiquidationFast()
        self.psychology = PsychologyFast()


# Алиасы для обратной совместимости
AdvancedAnalyzer = AdvancedAnalyzerTurbo
PsychologyLevels = PsychologyFast
