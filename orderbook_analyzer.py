"""
Orderbook Analyzer - анализ ордербука для определения уровней сопротивления
"""

from typing import Dict, List, Optional
import numpy as np
from logger import get_logger

logger = get_logger()


class OrderbookAnalyzer:
    """Класс для анализа ордербука"""
    
    def __init__(self, config: Dict):
        """
        Инициализация анализатора
        
        Args:
            config: Конфигурация из config.yaml секции 'short_entry'
        """
        self.min_sell_wall_pct = config['min_sell_wall_pct']
        self.depth = config['orderbook_depth']
    
    def analyze_orderbook(self, orderbook: Dict, current_price: float) -> Dict:
        """
        Анализ ордербука
        
        Args:
            orderbook: {"bids": [[price, quantity], ...], "asks": [[price, quantity], ...]}
            current_price: Текущая цена
            
        Returns:
            {
                "resistance_levels": [...],  # Уровни сопротивления (стены продаж)
                "support_levels": [...],     # Уровни поддержки
                "bid_ask_imbalance": float,  # -1 (все продажи) до +1 (все покупки)
                "largest_sell_wall": {"price": float, "quantity": float, "pct_of_total": float}
            }
        """
        if not orderbook or "asks" not in orderbook or "bids" not in orderbook:
            return {}
        
        asks = orderbook["asks"]  # Ордера на продажу
        bids = orderbook["bids"]  # Ордера на покупку
        
        if not asks or not bids:
            return {}
        
        try:
            # Конвертируем в массивы numpy
            ask_prices = np.array([float(ask[0]) for ask in asks])
            ask_quantities = np.array([float(ask[1]) for ask in asks])
            bid_prices = np.array([float(bid[0]) for bid in bids])
            bid_quantities = np.array([float(bid[1]) for bid in bids])
            
            # Общий объём
            total_ask_volume = np.sum(ask_quantities)
            total_bid_volume = np.sum(bid_quantities)
            total_volume = total_ask_volume + total_bid_volume
            
            if total_volume == 0:
                return {}
            
            # Находим крупные стены продаж (сопротивление)
            resistance_levels = []
            for i, (price, qty) in enumerate(zip(ask_prices, ask_quantities)):
                pct_of_total = (qty / total_volume) * 100
                if pct_of_total >= self.min_sell_wall_pct:
                    resistance_levels.append({
                        "price": float(price),
                        "quantity": float(qty),
                        "pct_of_total": float(pct_of_total)
                    })
            
            # Находим крупные стены покупок (поддержка)
            support_levels = []
            for i, (price, qty) in enumerate(zip(bid_prices, bid_quantities)):
                pct_of_total = (qty / total_volume) * 100
                if pct_of_total >= self.min_sell_wall_pct:
                    support_levels.append({
                        "price": float(price),
                        "quantity": float(qty),
                        "pct_of_total": float(pct_of_total)
                    })
            
            # Bid/Ask дисбаланс
            # Положительный = больше покупателей, отрицательный = больше продавцов
            bid_ask_imbalance = (total_bid_volume - total_ask_volume) / total_volume
            
            # Самая большая стена продаж
            largest_sell_wall = None
            if len(resistance_levels) > 0:
                largest_sell_wall = max(resistance_levels, key=lambda x: x["quantity"])
            
            result = {
                "resistance_levels": resistance_levels,
                "support_levels": support_levels,
                "bid_ask_imbalance": float(bid_ask_imbalance),
                "largest_sell_wall": largest_sell_wall,
                "total_ask_volume": float(total_ask_volume),
                "total_bid_volume": float(total_bid_volume)
            }
            
            if resistance_levels:
                logger.info(f"Найдено {len(resistance_levels)} уровней сопротивления")
            
            return result
        
        except Exception as e:
            logger.error(f"Ошибка анализа ордербука: {e}")
            return {}
    
    def find_nearest_resistance(self, orderbook_analysis: Dict, 
                               current_price: float) -> Optional[float]:
        """
        Найти ближайший уровень сопротивления выше текущей цены
        
        Args:
            orderbook_analysis: Результат analyze_orderbook()
            current_price: Текущая цена
            
        Returns:
            Цена ближайшего сопротивления или None
        """
        if not orderbook_analysis or "resistance_levels" not in orderbook_analysis:
            return None
        
        resistance_levels = orderbook_analysis["resistance_levels"]
        
        # Фильтруем только уровни выше текущей цены
        levels_above = [r for r in resistance_levels if r["price"] > current_price]
        
        if not levels_above:
            return None
        
        # Возвращаем ближайший
        nearest = min(levels_above, key=lambda x: x["price"])
        return nearest["price"]
    
    def calculate_orderbook_score(self, orderbook_analysis: Dict, 
                                 current_price: float) -> float:
        """
        Рассчитать score ордербука для входа в шорт (0-10)
        Высокий score = сильное сопротивление выше = хорошо для шорта
        
        Args:
            orderbook_analysis: Результат analyze_orderbook()
            current_price: Текущая цена
            
        Returns:
            Score от 0 до 10
        """
        if not orderbook_analysis:
            return 0.0
        
        score = 0.0
        
        # Проверяем наличие больших стен продаж
        if "resistance_levels" in orderbook_analysis:
            resistance_count = len(orderbook_analysis["resistance_levels"])
            if resistance_count > 0:
                score += min(resistance_count * 2.0, 5.0)
                
                # Бонус за очень крупную стену
                if "largest_sell_wall" in orderbook_analysis and orderbook_analysis["largest_sell_wall"]:
                    wall_pct = orderbook_analysis["largest_sell_wall"]["pct_of_total"]
                    if wall_pct >= 15:
                        score += 3.0
                    elif wall_pct >= 10:
                        score += 2.0
        
        # Проверяем дисбаланс (отрицательный = больше продавцов = хорошо)
        if "bid_ask_imbalance" in orderbook_analysis:
            imbalance = orderbook_analysis["bid_ask_imbalance"]
            if imbalance < -0.2:  # Продавцов значительно больше
                score += 2.0
            elif imbalance < -0.1:
                score += 1.0
        
        return min(score, 10.0)
    
    def track_whale_activity(self, current_orderbook: Dict, 
                            previous_orderbook: Optional[Dict] = None) -> Dict:
        """
        Отслеживание активности китов (крупных игроков)
        
        Args:
            current_orderbook: Текущий ордербук
            previous_orderbook: Предыдущий ордербук для сравнения
            
        Returns:
            {
                "whale_sells_appeared": bool,  # Появились крупные sell ордера
                "whale_buys_disappeared": bool,  # Исчезли крупные buy ордера
                "order_flow_bearish": bool,  # Общий флоу медвежий
                "whale_score": float  # Score 0-10
            }
        """
        result = {
            "whale_sells_appeared": False,
            "whale_buys_disappeared": False,
            "order_flow_bearish": False,
            "whale_score": 0.0
        }
        
        if not current_orderbook:
            return result
        
        try:
            current_analysis = self.analyze_orderbook(current_orderbook, 0)  # price не важна здесь
            
            if not current_analysis:
                return result
            
            # Проверяем появление крупных sell walls
            resistance_levels = current_analysis.get("resistance_levels", [])
            if resistance_levels:
                # Если есть очень крупные стены (>15% объёма)
                large_walls = [r for r in resistance_levels if r["pct_of_total"] >= 15]
                if large_walls:
                    result["whale_sells_appeared"] = True
                    result["whale_score"] += 4.0
                    logger.info(f"🐋 Обнаружена крупная стена продаж: {large_walls[0]['pct_of_total']:.1f}%")
            
            # Сравнение с предыдущим ордербуком
            if previous_orderbook:
                prev_analysis = self.analyze_orderbook(previous_orderbook, 0)
                
                if prev_analysis:
                    # Проверяем исчезновение buy support
                    prev_bid_volume = prev_analysis.get("total_bid_volume", 0)
                    curr_bid_volume = current_analysis.get("total_bid_volume", 0)
                    
                    if prev_bid_volume > 0:
                        bid_drop_pct = ((prev_bid_volume - curr_bid_volume) / prev_bid_volume) * 100
                        
                        if bid_drop_pct >= 30:  # Поддержка упала на 30%+
                            result["whale_buys_disappeared"] = True
                            result["whale_score"] += 3.0
                            logger.info(f"🐋 Buy support упал на {bid_drop_pct:.1f}%")
                    
                    # Проверяем изменение ask volume
                    prev_ask_volume = prev_analysis.get("total_ask_volume", 0)
                    curr_ask_volume = current_analysis.get("total_ask_volume", 0)
                    
                    if prev_ask_volume > 0:
                        ask_increase_pct = ((curr_ask_volume - prev_ask_volume) / prev_ask_volume) * 100
                        
                        if ask_increase_pct >= 30:  # Sell pressure вырос
                            result["whale_score"] += 2.0
            
            # Общий order flow анализ
            imbalance = current_analysis.get("bid_ask_imbalance", 0)
            if imbalance < -0.3:  # Сильный перевес продавцов
                result["order_flow_bearish"] = True
                result["whale_score"] += 1.0
            
            result["whale_score"] = min(result["whale_score"], 10.0)
            
            return result
        
        except Exception as e:
            logger.error(f"Ошибка whale tracking: {e}")
            return result
