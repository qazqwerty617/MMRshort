"""
🔥 LIQUIDATION HEATMAP v1.0
Анализ ликвидаций для фьючерсов.

Назначение:
1. СИГНАЛ: Если памп был для снятия ликвидности и больше нечего снимать = хороший шорт
2. TP TARGETS: Куда пойдёт цена, чтобы собрать ликвидность (магниты для цены)

Логика:
- Ликвидации лонгов происходят НИЖЕ цены (каскад маржин-коллов)
- Ликвидации шортов происходят ВЫШЕ цены
- Цена часто идёт туда, где скопились ликвидации (маркет-мейкер собирает их)
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class LiquidationHeatmap:
    """
    🔥 Анализатор ликвидаций.
    
    Рассчитывает зоны ликвидаций на основе:
    1. Open Interest и средних плечей
    2. Исторических уровней (где были крупные ликвидации раньше)
    3. Текущей структуры позиций
    """
    
    __slots__ = ('leverage_tiers', 'liq_history', 'max_history')
    
    def __init__(self):
        # Типичные плечи на MEXC
        self.leverage_tiers = [5, 10, 20, 50, 100]
        self.liq_history = defaultdict(list)  # symbol -> [liq_events]
        self.max_history = 100
    
    def calculate_liquidation_zones(self, 
                                   current_price: float,
                                   peak_price: float,
                                   start_price: float) -> Dict:
        """
        Рассчитать зоны ликвидаций относительно текущей цены.
        
        Returns:
            {
                "long_liq_zones": [...],  # Зоны ликвидации лонгов (ниже цены)
                "short_liq_zones": [...], # Зоны ликвидации шортов (выше цены)
                "nearest_long_liq": float,  # Ближайшая зона ликвидации лонгов
                "nearest_short_liq": float, # Ближайшая зона ликвидации шортов
                "liq_swept_above": bool,  # Была ли собрана ликвидность выше (шорты)
                "liq_remaining_below": bool,  # Есть ли ликвидность ниже (лонги)
            }
        """
        result = {
            "long_liq_zones": [],
            "short_liq_zones": [],
            "nearest_long_liq": None,
            "nearest_short_liq": None,
            "liq_swept_above": False,
            "liq_remaining_below": True,
            "liq_score": 5.0
        }
        
        try:
            # === LONG LIQUIDATION ZONES (Below current price) ===
            # Лонги ликвидируются когда цена падает на X% (зависит от плеча)
            # Формула: Liq_Price = Entry * (1 - 1/leverage)
            
            for lev in self.leverage_tiers:
                # Предполагаем, что лонги открыты от start_price до peak_price
                # Средняя точка входа лонгов
                avg_long_entry = (start_price + peak_price) / 2
                
                # Цена ликвидации для этого плеча
                liq_price = avg_long_entry * (1 - 0.9 / lev)  # 90% маржи = ликвидация
                
                if liq_price < current_price:
                    drop_pct = ((current_price - liq_price) / current_price) * 100
                    result["long_liq_zones"].append({
                        "price": liq_price,
                        "leverage": lev,
                        "drop_pct": drop_pct,
                        "intensity": self._estimate_intensity(lev)
                    })
            
            # === SHORT LIQUIDATION ZONES (Above current price) ===
            # Шорты ликвидируются когда цена растёт на X%
            # Формула: Liq_Price = Entry * (1 + 1/leverage)
            
            for lev in self.leverage_tiers:
                # Шорты могли открыться на пике
                avg_short_entry = peak_price
                
                # Цена ликвидации для шортов
                liq_price = avg_short_entry * (1 + 0.9 / lev)
                
                if liq_price > current_price:
                    rise_pct = ((liq_price - current_price) / current_price) * 100
                    result["short_liq_zones"].append({
                        "price": liq_price,
                        "leverage": lev,
                        "rise_pct": rise_pct,
                        "intensity": self._estimate_intensity(lev)
                    })
            
            # === ANALYSIS ===
            
            # Сортируем по близости к цене
            result["long_liq_zones"].sort(key=lambda x: x["drop_pct"])
            result["short_liq_zones"].sort(key=lambda x: x["rise_pct"])
            
            # Ближайшие зоны
            if result["long_liq_zones"]:
                result["nearest_long_liq"] = result["long_liq_zones"][0]["price"]
            
            if result["short_liq_zones"]:
                result["nearest_short_liq"] = result["short_liq_zones"][0]["price"]
            
            # Проверяем, была ли собрана ликвидность шортов (pump выше)
            # Если peak_price > avg_short_entry * 1.1 (10%+) - шорты были ликвидированы
            pump_pct = ((peak_price - start_price) / start_price) * 100
            if pump_pct >= 10:
                result["liq_swept_above"] = True
                logger.info(f"📊 Liq Sweep: Шорты ликвидированы при пампе +{pump_pct:.1f}%")
            
            # Есть ли ликвидность лонгов ниже
            if result["long_liq_zones"]:
                result["liq_remaining_below"] = True
            
            # === SCORE ===
            result["liq_score"] = self._calculate_score(result, pump_pct)
            
            return result
            
        except Exception as e:
            logger.error(f"Liquidation calc error: {e}")
            return result
    
    def _estimate_intensity(self, leverage: int) -> str:
        """Оценка интенсивности ликвидаций на этом плече."""
        # Более низкие плечи = больше позиций = больше ликвидаций
        if leverage <= 10:
            return "HIGH"  # Много позиций на 5x-10x
        elif leverage <= 25:
            return "MEDIUM"
        else:
            return "LOW"  # Мало позиций на 50x-100x
    
    def _calculate_score(self, analysis: Dict, pump_pct: float) -> float:
        """
        Рассчитать score для шорта на основе ликвидаций (0-10).
        Высокий score = ликвидность выше собрана, ниже много ликвидности = хорошо
        """
        score = 5.0
        
        # +2 если шорты были ликвидированы (ликвидность выше собрана)
        if analysis.get("liq_swept_above"):
            score += 2.0
        
        # +2 если много ликвидности лонгов ниже (цена пойдёт туда)
        long_zones = analysis.get("long_liq_zones", [])
        high_intensity_zones = [z for z in long_zones if z["intensity"] == "HIGH"]
        if len(high_intensity_zones) >= 2:
            score += 2.0
        elif len(high_intensity_zones) >= 1:
            score += 1.0
        
        # +1 за сильный памп (больше ликвидаций шортов)
        if pump_pct >= 20:
            score += 1.0
        
        return min(10.0, max(0.0, score))
    
    def get_tp_from_liquidations(self, 
                                analysis: Dict, 
                                entry_price: float) -> List[float]:
        """
        Получить TP targets на основе зон ликвидаций.
        Цена часто идёт к зонам ликвидаций (магнит).
        
        Returns:
            [tp1, tp2, tp3] - ценовые уровни для TP
        """
        long_zones = analysis.get("long_liq_zones", [])
        
        if not long_zones:
            # Fallback
            return [
                entry_price * 0.95,
                entry_price * 0.90,
                entry_price * 0.85
            ]
        
        # Берём первые 3 зоны ликвидаций лонгов как TP
        tps = []
        for zone in long_zones[:3]:
            tps.append(zone["price"])
        
        # Дополняем если мало
        while len(tps) < 3:
            last = tps[-1] if tps else entry_price * 0.95
            tps.append(last * 0.95)
        
        return tps
    
    def get_summary(self, analysis: Dict) -> str:
        """Текстовое саммари для логов."""
        parts = []
        
        if analysis.get("liq_swept_above"):
            parts.append("✅ Шорты ликвидированы")
        
        long_zones = analysis.get("long_liq_zones", [])
        if long_zones:
            nearest = long_zones[0]
            parts.append(f"🎯 Лонги @{nearest['price']:.8f} (-{nearest['drop_pct']:.1f}%)")
        
        score = analysis.get("liq_score", 5)
        if score >= 7:
            parts.append("🔥 Сильный магнит вниз")
        
        return " | ".join(parts) if parts else "Нейтрально"


# Глобальный экземпляр
_liq_heatmap = None

def get_liq_heatmap() -> LiquidationHeatmap:
    global _liq_heatmap
    if _liq_heatmap is None:
        _liq_heatmap = LiquidationHeatmap()
    return _liq_heatmap
