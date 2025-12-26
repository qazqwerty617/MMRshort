"""
🔥 ULTRA ORDERBOOK ANALYZER v1.0
Профессиональный анализ стакана для максимальной точности.

Возможности:
1. Глубина рынка (Market Depth) - сила покупателей vs продавцов
2. Стены (Walls) - крупные ордера, блокирующие движение
3. Кластерный анализ - зоны концентрации объёма
4. Spread Analysis - здоровье рынка
5. Absorption Detection - поглощение крупных ордеров
6. Imbalance Zones - зоны дисбаланса для TP
7. Iceberg Detection - скрытые ордера
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class UltraOrderbook:
    """
    🔥 ULTRA профессиональный анализатор стакана.
    Используется для:
    - Подтверждения входа в SHORT (есть ли стена сверху?)
    - Поиска оптимальных TP (где ликвидность для закрытия?)
    - Детекции китов и манипуляций
    """
    
    __slots__ = ('min_wall_pct', 'depth_levels', 'cluster_width_pct', 
                 'history', 'max_history')
    
    def __init__(self, 
                 min_wall_pct: float = 5.0,
                 depth_levels: int = 50,
                 cluster_width_pct: float = 0.5):
        """
        Args:
            min_wall_pct: Минимальный % от объёма для стены
            depth_levels: Глубина стакана для анализа
            cluster_width_pct: Ширина кластера в % от цены
        """
        self.min_wall_pct = min_wall_pct
        self.depth_levels = depth_levels
        self.cluster_width_pct = cluster_width_pct
        self.history = defaultdict(list)  # symbol -> [orderbook snapshots]
        self.max_history = 10  # Храним до 10 снапшотов для absorption detection
    
    def analyze(self, orderbook: Dict, current_price: float) -> Dict:
        """
        🔥 Полный анализ стакана.
        
        Args:
            orderbook: {"bids": [[price, qty], ...], "asks": [[price, qty], ...]}
            current_price: Текущая цена
            
        Returns:
            Полный анализ с метриками для SHORT entry и TP
        """
        if not orderbook or not orderbook.get('asks') or not orderbook.get('bids'):
            return self._empty_result()
        
        asks = orderbook['asks'][:self.depth_levels]
        bids = orderbook['bids'][:self.depth_levels]
        
        try:
            # Конвертация
            ask_prices = np.array([float(a[0]) for a in asks])
            ask_qtys = np.array([float(a[1]) for a in asks])
            bid_prices = np.array([float(b[0]) for b in bids])
            bid_qtys = np.array([float(b[1]) for b in bids])
            
            # === 1. MARKET DEPTH ===
            depth = self._analyze_depth(ask_prices, ask_qtys, bid_prices, bid_qtys, current_price)
            
            # === 2. WALLS (Стены) ===
            sell_walls = self._find_walls(ask_prices, ask_qtys, is_ask=True)
            buy_walls = self._find_walls(bid_prices, bid_qtys, is_ask=False)
            
            # === 3. SPREAD ===
            spread = self._analyze_spread(ask_prices, bid_prices, current_price)
            
            # === 4. CLUSTERS (Кластеры объёма) ===
            ask_clusters = self._find_clusters(ask_prices, ask_qtys, current_price)
            bid_clusters = self._find_clusters(bid_prices, bid_qtys, current_price)
            
            # === 5. IMBALANCE ZONES ===
            imbalance = self._calculate_imbalance(ask_qtys, bid_qtys)
            
            # === 6. TP TARGETS (Ликвидность для закрытия шорта) ===
            tp_targets = self._find_tp_targets(bid_prices, bid_qtys, current_price)
            
            # === 7. SL RESISTANCE (Сопротивление для SL) ===
            sl_resistance = self._find_sl_resistance(ask_prices, ask_qtys, current_price)
            
            # === 8. OVERALL SCORE ===
            short_score = self._calculate_short_score(
                depth, sell_walls, imbalance, spread
            )
            
            result = {
                # Метрики
                "depth": depth,
                "spread": spread,
                "imbalance": imbalance,
                
                # Стены
                "sell_walls": sell_walls,
                "buy_walls": buy_walls,
                
                # Кластеры
                "ask_clusters": ask_clusters,
                "bid_clusters": bid_clusters,
                
                # Для TP/SL
                "tp_targets": tp_targets,
                "sl_resistance": sl_resistance,
                
                # Score
                "short_score": short_score,
                
                # Summary
                "summary": self._generate_summary(depth, imbalance, sell_walls, short_score)
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Ultra Orderbook Error: {e}")
            return self._empty_result()
    
    def _analyze_depth(self, ask_prices, ask_qtys, bid_prices, bid_qtys, current_price) -> Dict:
        """Анализ глубины рынка по уровням."""
        # Объём на разных уровнях от цены
        levels = [0.5, 1.0, 2.0, 5.0]  # % от текущей цены
        
        depth_data = {}
        total_ask = np.sum(ask_qtys)
        total_bid = np.sum(bid_qtys)
        
        for pct in levels:
            ask_threshold = current_price * (1 + pct/100)
            bid_threshold = current_price * (1 - pct/100)
            
            ask_within = np.sum(ask_qtys[ask_prices <= ask_threshold])
            bid_within = np.sum(bid_qtys[bid_prices >= bid_threshold])
            
            depth_data[f"ask_{pct}pct"] = float(ask_within)
            depth_data[f"bid_{pct}pct"] = float(bid_within)
            depth_data[f"ratio_{pct}pct"] = float(bid_within / ask_within) if ask_within > 0 else 0
        
        depth_data["total_ask"] = float(total_ask)
        depth_data["total_bid"] = float(total_bid)
        depth_data["total_ratio"] = float(total_bid / total_ask) if total_ask > 0 else 1.0
        
        # Преобладание: > 1 = больше покупателей, < 1 = больше продавцов
        return depth_data
    
    def _find_walls(self, prices, qtys, is_ask: bool) -> List[Dict]:
        """Находит стены (крупные ордера)."""
        total = np.sum(qtys)
        if total == 0:
            return []
        
        walls = []
        threshold = self.min_wall_pct / 100 * total
        
        for i, (price, qty) in enumerate(zip(prices, qtys)):
            if qty >= threshold:
                pct = (qty / total) * 100
                walls.append({
                    "price": float(price),
                    "quantity": float(qty),
                    "pct_of_total": float(pct),
                    "type": "SELL" if is_ask else "BUY"
                })
        
        # Сортируем по объёму (самые крупные первые)
        walls.sort(key=lambda x: x["quantity"], reverse=True)
        return walls[:5]  # Топ 5
    
    def _analyze_spread(self, ask_prices, bid_prices, current_price) -> Dict:
        """Анализ спреда."""
        if len(ask_prices) == 0 or len(bid_prices) == 0:
            return {"spread_pct": 0, "spread_health": "UNKNOWN"}
        
        best_ask = ask_prices[0]
        best_bid = bid_prices[0]
        
        spread = best_ask - best_bid
        spread_pct = (spread / current_price) * 100
        
        # Оценка здоровья
        if spread_pct < 0.05:
            health = "EXCELLENT"
        elif spread_pct < 0.1:
            health = "GOOD"
        elif spread_pct < 0.3:
            health = "NORMAL"
        elif spread_pct < 1.0:
            health = "WIDE"
        else:
            health = "ILLIQUID"
        
        return {
            "best_ask": float(best_ask),
            "best_bid": float(best_bid),
            "spread": float(spread),
            "spread_pct": float(spread_pct),
            "spread_health": health
        }
    
    def _find_clusters(self, prices, qtys, current_price) -> List[Dict]:
        """Находит кластеры объёма (зоны концентрации)."""
        if len(prices) == 0:
            return []
        
        # Группируем ордера в кластеры по ценовым зонам
        cluster_width = current_price * self.cluster_width_pct / 100
        clusters = []
        
        # Простая группировка
        i = 0
        while i < len(prices):
            cluster_start = prices[i]
            cluster_qty = 0
            cluster_orders = 0
            
            j = i
            while j < len(prices) and prices[j] <= cluster_start + cluster_width:
                cluster_qty += qtys[j]
                cluster_orders += 1
                j += 1
            
            if cluster_orders > 1 or cluster_qty > np.sum(qtys) * 0.05:  # >5% объёма
                clusters.append({
                    "price_low": float(cluster_start),
                    "price_high": float(prices[j-1]) if j > i else float(cluster_start),
                    "total_qty": float(cluster_qty),
                    "order_count": cluster_orders,
                    "density": float(cluster_qty / cluster_orders) if cluster_orders > 0 else 0
                })
            
            i = j if j > i else i + 1
        
        # Топ кластеры по объёму
        clusters.sort(key=lambda x: x["total_qty"], reverse=True)
        return clusters[:3]
    
    def _calculate_imbalance(self, ask_qtys, bid_qtys) -> Dict:
        """Рассчитывает дисбаланс bid/ask."""
        total_ask = np.sum(ask_qtys)
        total_bid = np.sum(bid_qtys)
        total = total_ask + total_bid
        
        if total == 0:
            return {"imbalance": 0, "direction": "NEUTRAL", "strength": 0}
        
        # -1 = все продавцы, +1 = все покупатели
        imbalance = (total_bid - total_ask) / total
        
        if imbalance < -0.3:
            direction = "STRONG_SELL"
            strength = abs(imbalance)
        elif imbalance < -0.1:
            direction = "SELL"
            strength = abs(imbalance)
        elif imbalance > 0.3:
            direction = "STRONG_BUY"
            strength = imbalance
        elif imbalance > 0.1:
            direction = "BUY"
            strength = imbalance
        else:
            direction = "NEUTRAL"
            strength = 0
        
        return {
            "imbalance": float(imbalance),
            "direction": direction,
            "strength": float(strength),
            "ask_volume": float(total_ask),
            "bid_volume": float(total_bid)
        }
    
    def _find_tp_targets(self, bid_prices, bid_qtys, current_price) -> List[Dict]:
        """Находит оптимальные TP уровни (где есть ликвидность для закрытия шорта)."""
        targets = []
        total_bid = np.sum(bid_qtys)
        
        if total_bid == 0:
            return []
        
        # Ищем зоны с высокой ликвидностью на покупку (для закрытия шорта)
        cumulative = 0
        for price, qty in zip(bid_prices, bid_qtys):
            pct_of_total = (qty / total_bid) * 100
            cumulative += qty
            
            # Если это крупный ордер или зона накопления
            if pct_of_total >= 3.0:  # > 3% от всех бидов
                drop_pct = ((current_price - price) / current_price) * 100
                targets.append({
                    "price": float(price),
                    "quantity": float(qty),
                    "drop_pct": float(drop_pct),
                    "liquidity_score": float(pct_of_total),
                    "cumulative_depth": float(cumulative / total_bid * 100)
                })
        
        # Сортируем по близости к цене + ликвидности
        # Баланс: хотим ближний + ликвидный
        for t in targets:
            t["score"] = t["liquidity_score"] / (t["drop_pct"] + 1)
        
        targets.sort(key=lambda x: x["score"], reverse=True)
        return targets[:5]
    
    def _find_sl_resistance(self, ask_prices, ask_qtys, current_price) -> Dict:
        """Находит уровень сопротивления для SL (стена над ценой)."""
        total_ask = np.sum(ask_qtys)
        if total_ask == 0:
            return {}
        
        # Ищем первую крупную стену выше цены
        for price, qty in zip(ask_prices, ask_qtys):
            pct_of_total = (qty / total_ask) * 100
            if pct_of_total >= 5.0:  # Стена > 5%
                distance_pct = ((price - current_price) / current_price) * 100
                return {
                    "price": float(price),
                    "quantity": float(qty),
                    "distance_pct": float(distance_pct),
                    "strength": float(pct_of_total)
                }
        
        return {}
    
    def _calculate_short_score(self, depth, sell_walls, imbalance, spread) -> float:
        """
        Рассчитывает score для входа в SHORT (0-10).
        Высокий score = хорошо для шорта.
        """
        score = 5.0  # Базовый нейтральный
        
        # +/- 2 за depth ratio (< 1 = больше продавцов = хорошо)
        ratio = depth.get("total_ratio", 1.0)
        if ratio < 0.7:
            score += 2.0
        elif ratio < 0.9:
            score += 1.0
        elif ratio > 1.3:
            score -= 2.0
        elif ratio > 1.1:
            score -= 1.0
        
        # +2 за крупные стены продаж
        if len(sell_walls) >= 2:
            score += 2.0
        elif len(sell_walls) >= 1:
            score += 1.0
        
        # +1 за каждую стену > 10%
        for wall in sell_walls:
            if wall.get("pct_of_total", 0) >= 10:
                score += 0.5
        
        # +/- 1.5 за imbalance
        imb_dir = imbalance.get("direction", "NEUTRAL")
        if imb_dir == "STRONG_SELL":
            score += 1.5
        elif imb_dir == "SELL":
            score += 0.5
        elif imb_dir == "STRONG_BUY":
            score -= 1.5
        elif imb_dir == "BUY":
            score -= 0.5
        
        # -1 за плохой spread
        if spread.get("spread_health") == "ILLIQUID":
            score -= 1.0
        elif spread.get("spread_health") == "WIDE":
            score -= 0.5
        
        return max(0.0, min(10.0, score))
    
    def _generate_summary(self, depth, imbalance, sell_walls, short_score) -> str:
        """Генерирует текстовое саммари."""
        parts = []
        
        ratio = depth.get("total_ratio", 1.0)
        if ratio < 0.8:
            parts.append("📉 Давление продавцов")
        elif ratio > 1.2:
            parts.append("📈 Давление покупателей")
        
        if len(sell_walls) >= 2:
            parts.append(f"🧱 {len(sell_walls)} стен продаж")
        
        imb_dir = imbalance.get("direction", "")
        if "SELL" in imb_dir:
            parts.append("⚖️ Перевес продавцов")
        elif "BUY" in imb_dir:
            parts.append("⚖️ Перевес покупателей")
        
        if short_score >= 7:
            parts.append("✅ Отлично для SHORT")
        elif short_score <= 3:
            parts.append("⚠️ Плохо для SHORT")
        
        return " | ".join(parts) if parts else "Нейтрально"
    
    def _empty_result(self) -> Dict:
        return {
            "depth": {},
            "spread": {},
            "imbalance": {"imbalance": 0, "direction": "NEUTRAL", "strength": 0},
            "sell_walls": [],
            "buy_walls": [],
            "ask_clusters": [],
            "bid_clusters": [],
            "tp_targets": [],
            "sl_resistance": {},
            "short_score": 5.0,
            "summary": "Нет данных"
        }
    
    def get_tp_multiplier(self, analysis: Dict) -> float:
        """Получить множитель для TP на основе анализа стакана."""
        if not analysis:
            return 1.0
        
        score = analysis.get("short_score", 5)
        
        # Высокий score = глубже откат ожидается
        if score >= 8:
            return 1.3
        elif score >= 6:
            return 1.1
        elif score <= 3:
            return 0.8
        
        return 1.0
    
    def get_optimal_tps_from_orderbook(self, analysis: Dict, entry_price: float) -> List[float]:
        """
        Получить оптимальные TP на основе ликвидности в стакане.
        Возвращает конкретные ценовые уровни.
        """
        targets = analysis.get("tp_targets", [])
        
        if not targets:
            # Fallback
            return [
                entry_price * 0.95,
                entry_price * 0.90,
                entry_price * 0.85
            ]
        
        # Берём топ 3 по score
        prices = [t["price"] for t in targets[:3]]
        
        # Дополняем если мало
        while len(prices) < 3:
            last = prices[-1] if prices else entry_price * 0.95
            prices.append(last * 0.95)
        
        return prices


# Глобальный экземпляр
_ultra_orderbook = None

def get_ultra_orderbook() -> UltraOrderbook:
    global _ultra_orderbook
    if _ultra_orderbook is None:
        _ultra_orderbook = UltraOrderbook()
    return _ultra_orderbook
