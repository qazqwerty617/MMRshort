"""
Multi-Timeframe Analyzer - анализ трендов на разных таймфреймах
"""

from typing import Dict, List, Optional
from indicators import TechnicalIndicators
from logger import get_logger

logger = get_logger()


class MultiTimeframeAnalyzer:
    """Класс для анализа трендов на нескольких таймфреймах"""
    
    def __init__(self):
        """Инициализация анализатора"""
        self.indicators = TechnicalIndicators()
    
    async def analyze_trend(self, mexc_client, symbol: str) -> Dict:
        """
        Анализ тренда на разных таймфреймах
        
        Args:
            mexc_client: MEXC клиент для получения данных
            symbol: Символ пары
            
        Returns:
            {
                "1h_trend": "up"|"down"|"neutral",
                "4h_trend": "up"|"down"|"neutral",
                "1d_trend": "up"|"down"|"neutral",
                "overall_bearish": bool,
                "trend_strength": float (0-10)
            }
        """
        result = {
            "1h_trend": "neutral",
            "4h_trend": "neutral",
            "1d_trend": "neutral",
            "overall_bearish": False,
            "trend_strength": 0.0
        }
        
        try:
            # Получаем klines для разных таймфреймов
            klines_1h = await mexc_client.get_klines(symbol, interval="Hour1", limit=50)
            klines_4h = await mexc_client.get_klines(symbol, interval="Hour4", limit=50)
            klines_1d = await mexc_client.get_klines(symbol, interval="Day1", limit=30)
            
            # Анализируем каждый таймфрейм
            trends = {}
            
            if klines_1h and len(klines_1h) >= 20:
                trends["1h"] = self._analyze_timeframe_trend(
                    [k["close"] for k in klines_1h], 
                    ema_fast=9, 
                    ema_slow=21
                )
                result["1h_trend"] = trends["1h"]["direction"]
            
            if klines_4h and len(klines_4h) >= 20:
                trends["4h"] = self._analyze_timeframe_trend(
                    [k["close"] for k in klines_4h],
                    ema_fast=9,
                    ema_slow=21
                )
                result["4h_trend"] = trends["4h"]["direction"]
            
            if klines_1d and len(klines_1d) >= 20:
                trends["1d"] = self._analyze_timeframe_trend(
                    [k["close"] for k in klines_1d],
                    ema_fast=9,
                    ema_slow=21
                )
                result["1d_trend"] = trends["1d"]["direction"]
            
            # Определяем общий bearish тренд
            bearish_count = sum(1 for tf in trends.values() if tf["direction"] == "down")
            total_count = len(trends)
            
            if total_count > 0:
                result["overall_bearish"] = bearish_count >= (total_count / 2)
                
                # Сила тренда (0-10)
                # Все 3 таймфрейма bearish = 10
                # 2 из 3 bearish = 6-7
                # 1 из 3 bearish = 3-4
                if bearish_count == 3:
                    result["trend_strength"] = 10.0
                elif bearish_count == 2:
                    # Усиливаем если старшие таймфреймы bearish
                    if trends.get("4h", {}).get("direction") == "down":
                        result["trend_strength"] = 7.0
                    else:
                        result["trend_strength"] = 6.0
                elif bearish_count == 1:
                    result["trend_strength"] = 3.5
                else:
                    result["trend_strength"] = 0.0
            
            logger.info(f"MTF анализ {symbol}: 1h={result['1h_trend']}, "
                       f"4h={result['4h_trend']}, 1d={result['1d_trend']}, "
                       f"bearish={result['overall_bearish']}, strength={result['trend_strength']:.1f}")
            
            return result
        
        except Exception as e:
            logger.error(f"Ошибка MTF анализа для {symbol}: {e}")
            return result
    
    def _analyze_timeframe_trend(self, prices: List[float], 
                                 ema_fast: int = 9, 
                                 ema_slow: int = 21) -> Dict:
        """
        Анализ тренда на одном таймфрейме
        
        Args:
            prices: Список цен закрытия
            ema_fast: Период быстрой EMA
            ema_slow: Период медленной EMA
            
        Returns:
            {"direction": "up"|"down"|"neutral", "strength": float}
        """
        if len(prices) < ema_slow:
            return {"direction": "neutral", "strength": 0.0}
        
        # Рассчитываем EMA
        ema_f = self.indicators.calculate_ema(prices, ema_fast)
        ema_s = self.indicators.calculate_ema(prices, ema_slow)
        
        if ema_f is None or ema_s is None:
            return {"direction": "neutral", "strength": 0.0}
        
        current_price = prices[-1]
        
        # Определяем направление
        if ema_f < ema_s and current_price < ema_s:
            direction = "down"
            # Сила = насколько далеко цена от EMA
            distance_pct = ((ema_s - current_price) / ema_s) * 100
            strength = min(distance_pct * 2, 10.0)  # Максимум 10
        elif ema_f > ema_s and current_price > ema_s:
            direction = "up"
            distance_pct = ((current_price - ema_s) / ema_s) * 100
            strength = min(distance_pct * 2, 10.0)
        else:
            direction = "neutral"
            strength = 0.0
        
        return {"direction": direction, "strength": strength}
    
    def calculate_mtf_score(self, mtf_data: Dict) -> float:
        """
        Рассчитать score для шорта на основе MTF анализа
        
        Args:
            mtf_data: Результат analyze_trend()
            
        Returns:
            Score от 0 до 10
        """
        return mtf_data.get("trend_strength", 0.0)
    
    def format_mtf_info(self, mtf_data: Dict) -> str:
        """
        Форматировать MTF данные для отображения
        
        Args:
            mtf_data: Данные MTF анализа
            
        Returns:
            Строка для вывода
        """
        trend_1h = mtf_data.get("1h_trend", "neutral")
        trend_4h = mtf_data.get("4h_trend", "neutral")
        trend_1d = mtf_data.get("1d_trend", "neutral")
        overall_bearish = mtf_data.get("overall_bearish", False)
        
        def emoji(trend):
            if trend == "down":
                return "🔻"
            elif trend == "up":
                return "🔺"
            else:
                return "➖"
        
        msg = f"Тренды: 1ч {emoji(trend_1h)}, 4ч {emoji(trend_4h)}, 1д {emoji(trend_1d)}"
        
        if overall_bearish:
            msg += " ✅ Общий тренд медвежий"
        
        return msg
