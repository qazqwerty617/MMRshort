"""
Divergence Detector - обнаружение дивергенций между ценой и индикаторами
"""

from typing import List, Dict, Optional
from scipy.signal import find_peaks
import numpy as np
from logger import get_logger

logger = get_logger()


class DivergenceDetector:
    """Класс для обнаружения дивергенций"""
    
    def __init__(self):
        """Инициализация детектора"""
        pass
    
    def detect_bearish_divergence(self, prices: List[float], 
                                  indicator_values: List[float],
                                  min_distance: int = 5) -> Optional[Dict]:
        """
        Обнаружить медвежью дивергенцию (price makes higher high, indicator makes lower high)
        Это сигнал о возможном развороте вниз
        
        Args:
            prices: Список цен
            indicator_values: Значения индикатора (RSI, MACD, etc)
            min_distance: Минимальное расстояние между пиками
            
        Returns:
            {
                "type": "bearish",
                "strength": "слабая"|"средняя"|"сильная",
                "price_peak_1": float,
                "price_peak_2": float,
                "indicator_peak_1": float,
                "indicator_peak_2": float,
                "divergence_pct": float
            }
        """
        if len(prices) < 20 or len(indicator_values) < 20:
            return None
        
        try:
            # Находим пики в ценах
            price_peaks_idx, _ = find_peaks(prices, distance=min_distance)
            
            # Находим пики в индикаторе
            indicator_peaks_idx, _ = find_peaks(indicator_values, distance=min_distance)
            
            if len(price_peaks_idx) < 2 or len(indicator_peaks_idx) < 2:
                return None
            
            # Берём последние два пика
            price_peak_idx_1 = price_peaks_idx[-2]
            price_peak_idx_2 = price_peaks_idx[-1]
            
            # Ищем ближайшие пики индикатора к пикам цены
            indicator_peak_idx_1 = self._find_closest_peak(
                price_peak_idx_1, indicator_peaks_idx
            )
            indicator_peak_idx_2 = self._find_closest_peak(
                price_peak_idx_2, indicator_peaks_idx
            )
            
            if indicator_peak_idx_1 is None or indicator_peak_idx_2 is None:
                return None
            
            price_1 = prices[price_peak_idx_1]
            price_2 = prices[price_peak_idx_2]
            indicator_1 = indicator_values[indicator_peak_idx_1]
            indicator_2 = indicator_values[indicator_peak_idx_2]
            
            # Проверяем условие медвежьей дивергенции
            # Цена делает higher high, индикатор делает lower high
            if price_2 > price_1 and indicator_2 < indicator_1:
                # Рассчитываем силу дивергенции
                price_change_pct = ((price_2 - price_1) / price_1) * 100
                indicator_change_pct = ((indicator_1 - indicator_2) / indicator_1) * 100
                divergence_strength_pct = abs(price_change_pct + indicator_change_pct)
                
                # Определяем силу
                if divergence_strength_pct >= 10:
                    strength = "сильная"
                elif divergence_strength_pct >= 5:
                    strength = "средняя"
                else:
                    strength = "слабая"
                
                logger.info(f"Обнаружена медвежья дивергенция ({strength}): "
                          f"цена {price_1:.6f} -> {price_2:.6f}, "
                          f"индикатор {indicator_1:.2f} -> {indicator_2:.2f}")
                
                return {
                    "type": "bearish",
                    "strength": strength,
                    "price_peak_1": price_1,
                    "price_peak_2": price_2,
                    "indicator_peak_1": indicator_1,
                    "indicator_peak_2": indicator_2,
                    "divergence_pct": divergence_strength_pct
                }
        
        except Exception as e:
            logger.error(f"Ошибка обнаружения дивергенции: {e}")
        
        return None
    
    def detect_rsi_divergence(self, prices: List[float], 
                             rsi_values: List[float]) -> Optional[Dict]:
        """
        Обнаружить дивергенцию по RSI
        
        Args:
            prices: Список цен
            rsi_values: Список значений RSI
            
        Returns:
            Данные о дивергенции
        """
        return self.detect_bearish_divergence(prices, rsi_values)
    
    def detect_macd_divergence(self, prices: List[float], 
                              macd_values: List[float]) -> Optional[Dict]:
        """
        Обнаружить дивергенцию по MACD
        
        Args:
            prices: Список цен
            macd_values: Список значений MACD
            
        Returns:
            Данные о дивергенции
        """
        return self.detect_bearish_divergence(prices, macd_values)
    
    def _find_closest_peak(self, target_idx: int, peak_indices: np.ndarray) -> Optional[int]:
        """
        Найти ближайший пик к целевому индексу
        
        Args:
            target_idx: Целевой индекс
            peak_indices: Массив индексов пиков
            
        Returns:
            Индекс ближайшего пика или None
        """
        if len(peak_indices) == 0:
            return None
        
        # Находим пик с минимальной разницей по индексу
        distances = np.abs(peak_indices - target_idx)
        closest_idx = np.argmin(distances)
        
        # Проверяем что расстояние не слишком большое (макс 10 свечей)
        if distances[closest_idx] <= 10:
            return peak_indices[closest_idx]
        
        return None
    
    def calculate_divergence_score(self, prices: List[float], 
                                   rsi_values: List[float],
                                   macd_values: Optional[List[float]] = None) -> float:
        """
        Рассчитать общий score дивергенции (0-10)
        
        Args:
            prices: Список цен
            rsi_values: Значения RSI
            macd_values: Значения MACD (опционально)
            
        Returns:
            Score от 0 до 10
        """
        score = 0.0
        
        # Проверяем RSI дивергенцию
        rsi_div = self.detect_rsi_divergence(prices, rsi_values)
        if rsi_div:
            if rsi_div["strength"] == "сильная":
                score += 5.0
            elif rsi_div["strength"] == "средняя":
                score += 3.0
            else:
                score += 1.5
        
        # Проверяем MACD дивергенцию
        if macd_values:
            macd_div = self.detect_macd_divergence(prices, macd_values)
            if macd_div:
                if macd_div["strength"] == "сильная":
                    score += 5.0
                elif macd_div["strength"] == "средняя":
                    score += 3.0
                else:
                    score += 1.5
        
        # Ограничиваем максимум 10
        return min(score, 10.0)
