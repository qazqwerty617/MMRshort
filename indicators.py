"""
Indicators - технические индикаторы для анализа
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from logger import get_logger

logger = get_logger()


class TechnicalIndicators:
    """Класс для расчёта технических индикаторов"""
    
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
        """
        Расчёт RSI (Relative Strength Index)
        
        Args:
            prices: Список цен закрытия
            period: Период RSI
            
        Returns:
            Значение RSI или None
        """
        if len(prices) < period + 1:
            return None
        
        try:
            prices_arr = np.array(prices)
            
            # Рассчитываем изменения цены
            deltas = np.diff(prices_arr)
            
            # Разделяем на прибыли и убытки
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            
            # Расчёт среднего прироста и убытка (EMA-стиль)
            avg_gain = np.mean(gains[:period])
            avg_loss = np.mean(losses[:period])
            
            for i in range(period, len(gains)):
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
            if avg_loss == 0:
                return 100.0
            
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
            return float(rsi)
        except Exception as e:
            logger.error(f"Ошибка расчёта RSI: {e}")
            return None
    
    @staticmethod
    def calculate_macd(prices: List[float], fast: int = 12, 
                      slow: int = 26, signal: int = 9) -> Optional[Dict]:
        """
        Расчёт MACD (Moving Average Convergence Divergence)
        
        Args:
            prices: Список цен закрытия
            fast: Период быстрой EMA
            slow: Период медленной EMA
            signal: Период сигнальной линии
            
        Returns:
            {"macd": value, "signal": value, "histogram": value}
        """
        if len(prices) < slow + signal:
            return None
        
        try:
            prices_series = pd.Series(prices)
            
            # Рассчитываем EMA
            ema_fast = prices_series.ewm(span=fast, adjust=False).mean()
            ema_slow = prices_series.ewm(span=slow, adjust=False).mean()
            
            # MACD линия
            macd_line = ema_fast - ema_slow
            
            # Сигнальная линия
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            
            # Гистограмма
            histogram = macd_line - signal_line
            
            return {
                "macd": float(macd_line.iloc[-1]),
                "signal": float(signal_line.iloc[-1]),
                "histogram": float(histogram.iloc[-1])
            }
        except Exception as e:
            logger.error(f"Ошибка расчёта MACD: {e}")
            return None
    
    @staticmethod
    def calculate_bollinger_bands(prices: List[float], period: int = 20, 
                                 std_dev: float = 2.0) -> Optional[Dict]:
        """
        Расчёт Bollinger Bands
        
        Args:
            prices: Список цен закрытия
            period: Период SMA
            std_dev: Множитель стандартного отклонения
            
        Returns:
            {"upper": value, "middle": value, "lower": value, "bandwidth": value}
        """
        if len(prices) < period:
            return None
        
        try:
            prices_series = pd.Series(prices)
            
            # Средняя линия (SMA)
            middle = prices_series.rolling(window=period).mean()
            
            # Стандартное отклонение
            std = prices_series.rolling(window=period).std()
            
            # Верхняя и нижняя полосы
            upper = middle + (std * std_dev)
            lower = middle - (std * std_dev)
            
            # Bandwidth
            bandwidth = ((upper.iloc[-1] - lower.iloc[-1]) / middle.iloc[-1]) * 100
            
            return {
                "upper": float(upper.iloc[-1]),
                "middle": float(middle.iloc[-1]),
                "lower": float(lower.iloc[-1]),
                "bandwidth": float(bandwidth)
            }
        except Exception as e:
            logger.error(f"Ошибка расчёта Bollinger Bands: {e}")
            return None
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> Optional[float]:
        """
        Расчёт EMA (Exponential Moving Average)
        
        Args:
            prices: Список цен
            period: Период EMA
            
        Returns:
            Значение EMA
        """
        if len(prices) < period:
            return None
        
        try:
            df = pd.DataFrame({'close': prices})
            ema = ta.ema(df['close'], length=period)
            return float(ema.iloc[-1]) if ema is not None else None
        except Exception as e:
            logger.error(f"Ошибка расчёта EMA: {e}")
            return None
    
    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> Optional[float]:
        """
        Расчёт SMA (Simple Moving Average)
        
        Args:
            prices: Список цен
            period: Период SMA
            
        Returns:
            Значение SMA
        """
        if len(prices) < period:
            return None
        
        try:
            return float(np.mean(prices[-period:]))
        except Exception as e:
            logger.error(f"Ошибка расчёта SMA: {e}")
            return None
    
    @staticmethod
    def calculate_atr(highs: List[float], lows: List[float], 
                     closes: List[float], period: int = 14) -> Optional[float]:
        """
        Расчёт ATR (Average True Range) для стоп-лосса
        
        Args:
            highs: Список максимумов
            lows: Список минимумов
            closes: Список закрытий
            period: Период ATR
            
        Returns:
            Значение ATR
        """
        if len(highs) < period or len(lows) < period or len(closes) < period:
            return None
        
        try:
            df = pd.DataFrame({
                'high': highs,
                'low': lows,
                'close': closes
            })
            atr = ta.atr(df['high'], df['low'], df['close'], length=period)
            return float(atr.iloc[-1]) if atr is not None else None
        except Exception as e:
            logger.error(f"Ошибка расчёта ATR: {e}")
            return None
    
    @staticmethod
    def calculate_stochastic(highs: List[float], lows: List[float], 
                           closes: List[float], k_period: int = 14,
                           d_period: int = 3) -> Optional[Dict]:
        """
        Расчёт Stochastic Oscillator
        
        Args:
            highs: Список максимумов
            lows: Список минимумов
            closes: Список закрытий
            k_period: Период %K
            d_period: Период %D
            
        Returns:
            {"k": value, "d": value}
        """
        if len(highs) < k_period:
            return None
        
        try:
            df = pd.DataFrame({
                'high': highs,
                'low': lows,
                'close': closes
            })
            stoch = ta.stoch(df['high'], df['low'], df['close'], 
                           k=k_period, d=d_period)
            
            if stoch is not None:
                return {
                    "k": float(stoch[f'STOCHk_{k_period}_{d_period}_{d_period}'].iloc[-1]),
                    "d": float(stoch[f'STOCHd_{k_period}_{d_period}_{d_period}'].iloc[-1])
                }
        except Exception as e:
            logger.error(f"Ошибка расчёта Stochastic: {e}")
        
        return None
    
    @staticmethod
    def find_support_resistance(prices: List[float], tolerance: float = 0.02) -> Dict:
        """
        Поиск уровней поддержки и сопротивления
        
        Args:
            prices: Список цен
            tolerance: Допуск для группировки уровней (2% по умолчанию)
            
        Returns:
            {"support": [levels], "resistance": [levels]}
        """
        if len(prices) < 10:
            return {"support": [], "resistance": []}
        
        try:
            current_price = prices[-1]
            
            # Находим локальные максимумы и минимумы
            from scipy.signal import find_peaks
            
            peaks_idx, _ = find_peaks(prices, distance=5)
            troughs_idx, _ = find_peaks([-p for p in prices], distance=5)
            
            # Группируем близкие уровни
            def cluster_levels(values, tol):
                if not values:
                    return []
                clusters = []
                current_cluster = [values[0]]
                
                for val in values[1:]:
                    if abs(val - np.mean(current_cluster)) / np.mean(current_cluster) < tol:
                        current_cluster.append(val)
                    else:
                        clusters.append(np.mean(current_cluster))
                        current_cluster = [val]
                
                if current_cluster:
                    clusters.append(np.mean(current_cluster))
                
                return clusters
            
            resistance_values = [prices[i] for i in peaks_idx if prices[i] > current_price]
            support_values = [prices[i] for i in troughs_idx if prices[i] < current_price]
            
            return {
                "support": cluster_levels(support_values, tolerance),
                "resistance": cluster_levels(resistance_values, tolerance)
            }
        except Exception as e:
            logger.error(f"Ошибка поиска уровней: {e}")
            return {"support": [], "resistance": []}
