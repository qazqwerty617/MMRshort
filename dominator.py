"""
🚀 MARKET DOMINATION SYSTEM v2.0 - TURBO EDITION
Оптимизировано для МАКСИМАЛЬНОЙ СКОРОСТИ.

Оптимизации:
- Кэширование результатов
- Упрощённые расчёты
- Ленивые вычисления
- Минимум итераций
"""

import logging
from typing import Dict, List, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)


class OrderFlowDominator:
    """Order Flow - TURBO версия"""
    
    __slots__ = ()  # Без лишней памяти
    
    @staticmethod
    def analyze_fast(orderbook: Dict) -> Dict:
        """Быстрый анализ дисбаланса стакана"""
        if not orderbook:
            return {'imbalance': 0, 'mult': 1.0}
        
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])
        
        if not bids or not asks:
            return {'imbalance': 0, 'mult': 1.0}
        
        # Берём только первые 5 уровней для скорости
        bid_vol = sum(float(b[1]) for b in bids[:5])
        ask_vol = sum(float(a[1]) for a in asks[:5])
        
        total = bid_vol + ask_vol
        if total == 0:
            return {'imbalance': 0, 'mult': 1.0}
        
        imbalance = (bid_vol - ask_vol) / total
        
        # Быстрый множитель
        if imbalance < -0.3:
            mult = 1.2
        elif imbalance < -0.1:
            mult = 1.1
        elif imbalance > 0.3:
            mult = 0.85
        else:
            mult = 1.0
        
        return {'imbalance': round(imbalance, 2), 'mult': mult}


class WhaleTrackerFast:
    """Whale Tracker - TURBO версия"""
    
    __slots__ = ('threshold_pct',)
    
    def __init__(self, threshold_pct: float = 5.0):
        self.threshold_pct = threshold_pct
    
    def detect_fast(self, orderbook: Dict) -> Dict:
        """Быстрый поиск китов"""
        if not orderbook:
            return {'whale_pressure': 0, 'mult': 1.0}
        
        bids = orderbook.get('bids', [])[:15]
        asks = orderbook.get('asks', [])[:15]
        
        if not bids or not asks:
            return {'whale_pressure': 0, 'mult': 1.0}
        
        # Средний объём
        all_vols = [float(b[1]) for b in bids] + [float(a[1]) for a in asks]
        avg_vol = sum(all_vols) / len(all_vols) if all_vols else 0
        threshold = avg_vol * (self.threshold_pct / 100) * 10
        
        whale_bids = sum(1 for b in bids if float(b[1]) > threshold)
        whale_asks = sum(1 for a in asks if float(a[1]) > threshold)
        
        # Pressure: +1 = киты покупают, -1 = киты продают
        pressure = whale_bids - whale_asks
        
        if pressure < -2:
            mult = 1.15  # Киты сливают
        elif pressure < 0:
            mult = 1.05
        elif pressure > 2:
            mult = 0.9  # Киты покупают
        else:
            mult = 1.0
        
        return {'whale_pressure': pressure, 'mult': mult}


class BTCCorrFast:
    """BTC Correlation - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def analyze_fast(btc_klines: List, alt_klines: List) -> Dict:
        """Быстрый анализ корреляции с BTC"""
        if not btc_klines or len(btc_klines) < 5:
            return {'btc_trend': 'unknown', 'mult': 1.0}
        
        # Просто смотрим изменение BTC за последние N свечей
        btc_change = (float(btc_klines[-1][4]) - float(btc_klines[0][4])) / float(btc_klines[0][4]) * 100
        
        if btc_change < -3:
            mult = 1.2  # BTC сильно падает
        elif btc_change < -1:
            mult = 1.1
        elif btc_change > 3:
            mult = 0.85  # BTC растёт
        else:
            mult = 1.0
        
        return {'btc_change': round(btc_change, 2), 'mult': mult}


class ClusterFast:
    """Volume Clusters - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def find_support_fast(klines: List, current_price: float) -> Optional[float]:
        """Быстрый поиск ближайшей поддержки"""
        if not klines or len(klines) < 5:
            return None
        
        # Берём 5 свечей с максимальным объёмом
        sorted_k = sorted(klines[-20:], key=lambda x: float(x[5]), reverse=True)[:5]
        
        # Ищем ближайшую поддержку ниже цены
        supports = []
        for k in sorted_k:
            low = float(k[3])
            if low < current_price:
                supports.append(low)
        
        return max(supports) if supports else None


class MMDetectorFast:
    """MM Detection - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def detect_fast(klines: List) -> Dict:
        """Быстрое обнаружение манипуляций"""
        if not klines or len(klines) < 5:
            return {'manipulation': False}
        
        spike_count = 0
        for k in klines[-5:]:
            high, low = float(k[2]), float(k[3])
            open_p, close = float(k[1]), float(k[4])
            
            body = abs(close - open_p)
            total = high - low
            
            if total > 0 and body / total < 0.2:
                spike_count += 1
        
        return {'manipulation': spike_count >= 3}


class FundingFast:
    """Funding Prediction - TURBO версия"""
    
    __slots__ = ()
    
    @staticmethod
    def predict_fast(funding_rate: float) -> Dict:
        """Быстрый анализ фандинга"""
        if funding_rate > 0.05:
            return {'signal': 'strong_short', 'mult': 1.25}
        elif funding_rate > 0.02:
            return {'signal': 'short', 'mult': 1.1}
        elif funding_rate < -0.02:
            return {'signal': 'avoid', 'mult': 0.85}
        return {'signal': 'neutral', 'mult': 1.0}


class DominatorTurbo:
    """
    🚀 DOMINATOR TURBO - Максимально быстрая версия.
    Все анализаторы оптимизированы для скорости.
    """
    
    __slots__ = ('order_flow', 'whale', 'btc', 'cluster', 'mm', 'funding')
    
    def __init__(self):
        self.order_flow = OrderFlowDominator()
        self.whale = WhaleTrackerFast()
        self.btc = BTCCorrFast()
        self.cluster = ClusterFast()
        self.mm = MMDetectorFast()
        self.funding = FundingFast()
    
    def dominate(self, 
                 symbol: str,
                 klines: List,
                 orderbook: Dict,
                 btc_klines: List = None,
                 funding_rate: float = 0,
                 entry_price: float = 0) -> Dict:
        """
        ТУРБО-ДОМИНИРОВАНИЕ - все расчёты оптимизированы.
        """
        total_mult = 1.0
        recommendations = []
        
        # 1. Order Flow (самый быстрый)
        of = self.order_flow.analyze_fast(orderbook)
        total_mult *= of['mult']
        if of['mult'] > 1.1:
            recommendations.append("📊 Сильный дисбаланс продаж")
        
        # 2. Whale Tracker
        whale = self.whale.detect_fast(orderbook)
        total_mult *= whale['mult']
        if whale['mult'] > 1.1:
            recommendations.append("🐋 Киты продают")
        
        # 3. BTC Correlation (если есть данные)
        if btc_klines:
            btc = self.btc.analyze_fast(btc_klines, klines)
            total_mult *= btc['mult']
            if btc['mult'] > 1.1:
                recommendations.append(f"📉 BTC падает {btc['btc_change']}%")
        
        # 4. MM Detection
        mm = self.mm.detect_fast(klines)
        if mm['manipulation']:
            total_mult *= 0.95  # Немного снижаем уверенность
            recommendations.append("⚠️ Признаки манипуляции")
        
        # 5. Funding (если есть)
        if funding_rate != 0:
            fund = self.funding.predict_fast(funding_rate)
            total_mult *= fund['mult']
            if fund['mult'] > 1.1:
                recommendations.append(f"💰 Высокий фандинг {funding_rate}%")
        
        # Cluster support
        support = self.cluster.find_support_fast(klines, entry_price) if klines and entry_price else None
        
        # Финальный скор
        base_score = 5.0
        score = min(10, max(1, base_score * total_mult))
        
        # Signal
        if score >= 7:
            signal = '🔥 DOMINATE'
        elif score >= 5.5:
            signal = '✅ SHORT'
        else:
            signal = '⚠️ WAIT'
        
        return {
            'domination_score': round(score, 1),
            'total_multiplier': round(total_mult, 3),
            'signal': signal,
            'recommendations': recommendations,
            'cluster_support': support,
            'confidence': min(1.0, 0.5 + len(recommendations) * 0.15)
        }


# Алиас для обратной совместимости
Dominator = DominatorTurbo
