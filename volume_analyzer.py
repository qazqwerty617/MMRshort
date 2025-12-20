"""
Volume Analyzer - анализ объёмов для определения точки входа
"""

from typing import List, Optional, Dict
import numpy as np
from logger import get_logger

logger = get_logger()


class VolumeAnalyzer:
    """Класс для анализа объёмов"""
    
    def __init__(self, config: Dict):
        """
        Инициализация анализатора
        
        Args:
            config: Конфигурация из config.yaml секции 'short_entry'
        """
        self.min_volume_drop = config['min_volume_drop_pct']
    
    def detect_volume_drop(self, volumes: List[float], 
                          lookback_peak: int = 5,
                          lookback_current: int = 3) -> Optional[Dict]:
        """
        Обнаружить падение объёма после пампа
        
        Args:
            volumes: Список объёмов (последние = текущие)
            lookback_peak: Сколько свечей назад искать пиковый объём
            lookback_current: Сколько последних свечей усреднять для текущего объёма
            
        Returns:
            {
                "volume_drop_pct": float,
                "peak_volume": float,
                "current_volume": float,
                "is_significant": bool
            }
        """
        if len(volumes) < lookback_peak + lookback_current:
            return None
        
        # Пиковый объём (во время/сразу после пампа)
        peak_volume = max(volumes[-lookback_peak-lookback_current:-lookback_current])
        
        # Текущий средний объём
        current_avg_volume = np.mean(volumes[-lookback_current:])
        
        if peak_volume == 0:
            return None
        
        # Падение в процентах
        volume_drop_pct = ((peak_volume - current_avg_volume) / peak_volume) * 100
        
        is_significant = volume_drop_pct >= self.min_volume_drop
        
        # Логируем результат анализа
        logger.info(f"📉 Volume Analysis: Peak={peak_volume:.2f}, Current={current_avg_volume:.2f}, Drop={volume_drop_pct:.1f}% (threshold={self.min_volume_drop}%)")
        
        if is_significant:
            logger.info(f"✅ Обнаружено значительное падение объёма: -{volume_drop_pct:.1f}%")
        else:
            logger.debug(f"⚠️ Падение объёма недостаточное: -{volume_drop_pct:.1f}% < {self.min_volume_drop}%")
        
        return {
            "volume_drop_pct": volume_drop_pct,
            "peak_volume": peak_volume,
            "current_volume": current_avg_volume,
            "is_significant": is_significant
        }
    
    def calculate_volume_profile(self, volumes: List[float], 
                                prices: List[float],
                                bins: int = 10) -> Dict:
        """
        Построить профиль объёма (volume profile)
        
        Args:
            volumes: Список объёмов
            prices: Список цен
            bins: Количество ценовых уровней
            
        Returns:
            {
                "price_levels": [...],
                "volume_at_level": [...],
                "high_volume_node": float,  # Уровень с максимальным объёмом
                "low_volume_node": float     # Уровень с минимальным объёмом
            }
        """
        if len(volumes) != len(prices) or len(volumes) < bins:
            return {}
        
        try:
            # Создаём ценовые bins
            min_price = min(prices)
            max_price = max(prices)
            price_bins = np.linspace(min_price, max_price, bins + 1)
            
            # Суммируем объём для каждого bin
            volume_at_bins = np.zeros(bins)
            
            for i, (price, volume) in enumerate(zip(prices, volumes)):
                # Находим к какому bin относится цена
                bin_idx = min(int((price - min_price) / (max_price - min_price) * bins), bins - 1)
                volume_at_bins[bin_idx] += volume
            
            # Находим уровни с максимальным и минимальным объёмом
            max_volume_idx = np.argmax(volume_at_bins)
            min_volume_idx = np.argmin(volume_at_bins)
            
            high_volume_node = (price_bins[max_volume_idx] + price_bins[max_volume_idx + 1]) / 2
            low_volume_node = (price_bins[min_volume_idx] + price_bins[min_volume_idx + 1]) / 2
            
            return {
                "price_levels": [(price_bins[i] + price_bins[i+1])/2 for i in range(bins)],
                "volume_at_level": volume_at_bins.tolist(),
                "high_volume_node": high_volume_node,
                "low_volume_node": low_volume_node
            }
        
        except Exception as e:
            logger.error(f"Ошибка построения volume profile: {e}")
            return {}
    
    def calculate_volume_score(self, volumes: List[float]) -> float:
        """
        Рассчитать score объёма для входа в шорт (0-10)
        Высокий score = объём сильно упал = хорошо для шорта
        
        Args:
            volumes: Список объёмов
            
        Returns:
            Score от 0 до 10
        """
        volume_drop = self.detect_volume_drop(volumes)
        
        if not volume_drop:
            return 0.0
        
        drop_pct = volume_drop["volume_drop_pct"]
        
        # Линейная шкала: 40% падения = 5.0, 80% падения = 10.0
        score = (drop_pct / 40.0) * 5.0
        
        return min(max(score, 0.0), 10.0)
