"""
⏱️ MULTI-TIMEFRAME ANALYZER v1.0 - Анализ тренда на высших таймфреймах

ФИЛОСОФИЯ:
Не шортить против сильного тренда на высших TF.
5-min может быть вверх, но 1h вниз = хороший шорт.
5-min вверх И 1h вверх = плохой шорт.

ФУНКЦИИ:
1. Анализ 5m, 15m, 1h, 4h свечей
2. Определение тренда (UP/DOWN/SIDEWAYS)
3. Проверка confluence (совпадение трендов)
4. Score для short (чем больше TF вниз - тем лучше)
"""

import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class MultiTimeframeAnalyzer:
    """
    ⏱️ MULTI-TIMEFRAME ANALYZER
    
    Проверяет тренд на нескольких таймфреймах для подтверждения сигнала.
    """
    
    def __init__(self, rest_url: str = "https://contract.mexc.com"):
        self.rest_url = rest_url
        self.session = None
        
        # Таймфреймы для анализа (MEXC kline intervals)
        self.timeframes = {
            '5m': {'interval': 'Min5', 'candles': 20, 'weight': 0.15},
            '15m': {'interval': 'Min15', 'candles': 20, 'weight': 0.25},
            '1h': {'interval': 'Min60', 'candles': 20, 'weight': 0.35},
            '4h': {'interval': 'Hour4', 'candles': 20, 'weight': 0.25}
        }
    
    async def get_klines(self, symbol: str, interval: str, limit: int = 20) -> List[Dict]:
        """Получить свечи с MEXC."""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            url = f"{self.rest_url}/api/v1/contract/kline/{symbol}"
            params = {"interval": interval, "limit": limit}
            
            async with self.session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('success') and data.get('data'):
                        return data['data']
        except Exception as e:
            logger.debug(f"MTF klines error {symbol}/{interval}: {e}")
        return []
    
    def analyze_trend(self, klines: List[Dict]) -> Dict:
        """
        Анализ тренда по свечам.
        
        Returns:
            {
                'trend': 'UP' / 'DOWN' / 'SIDEWAYS',
                'strength': float (0-10),
                'ema_cross': 'BULLISH' / 'BEARISH' / 'NONE',
                'momentum': float (-100 to +100)
            }
        """
        if not klines or len(klines) < 10:
            return {'trend': 'UNKNOWN', 'strength': 0, 'ema_cross': 'NONE', 'momentum': 0}
        
        try:
            # Извлекаем close prices
            closes = []
            for k in klines:
                if isinstance(k, dict):
                    closes.append(float(k.get('close', k.get('c', 0))))
                elif isinstance(k, list) and len(k) >= 5:
                    closes.append(float(k[4]))
            
            if len(closes) < 10:
                return {'trend': 'UNKNOWN', 'strength': 0, 'ema_cross': 'NONE', 'momentum': 0}
            
            # EMA расчёт (простой)
            def ema(data, period):
                if len(data) < period:
                    return sum(data) / len(data)
                multiplier = 2 / (period + 1)
                ema_val = sum(data[:period]) / period
                for price in data[period:]:
                    ema_val = (price - ema_val) * multiplier + ema_val
                return ema_val
            
            ema_fast = ema(closes, 8)
            ema_slow = ema(closes, 21)
            current_price = closes[-1]
            
            # Тренд на основе EMA
            if ema_fast > ema_slow * 1.005:
                trend = 'UP'
                ema_cross = 'BULLISH'
            elif ema_fast < ema_slow * 0.995:
                trend = 'DOWN'
                ema_cross = 'BEARISH'
            else:
                trend = 'SIDEWAYS'
                ema_cross = 'NONE'
            
            # Momentum (изменение за период)
            if len(closes) >= 10:
                momentum = ((closes[-1] - closes[-10]) / closes[-10]) * 100
            else:
                momentum = 0
            
            # Strength (насколько уверенный тренд)
            price_vs_ema = abs(current_price - ema_slow) / ema_slow * 100
            strength = min(10, price_vs_ema * 2)
            
            # Для DOWN тренда - momentum отрицательный = хорошо
            if trend == 'DOWN':
                strength = min(10, strength + abs(momentum) * 0.5)
            
            return {
                'trend': trend,
                'strength': round(strength, 1),
                'ema_cross': ema_cross,
                'momentum': round(momentum, 2)
            }
            
        except Exception as e:
            logger.error(f"Trend analysis error: {e}")
            return {'trend': 'ERROR', 'strength': 0, 'ema_cross': 'NONE', 'momentum': 0}
    
    async def analyze(self, symbol: str, session: aiohttp.ClientSession = None) -> Dict:
        """
        Полный Multi-Timeframe анализ.
        
        Returns:
            {
                'short_score': float (0-10),  # Чем выше = лучше для шорта
                'confluence': str ('STRONG_SHORT', 'WEAK_SHORT', 'NEUTRAL', 'AVOID_SHORT'),
                'timeframes': {
                    '5m': {...},
                    '15m': {...},
                    ...
                },
                'summary': str
            }
        """
        if session:
            self.session = session
        
        result = {
            'short_score': 5.0,
            'confluence': 'NEUTRAL',
            'timeframes': {},
            'summary': ''
        }
        
        try:
            weighted_score = 0
            total_weight = 0
            down_count = 0
            up_count = 0
            
            for tf_name, tf_config in self.timeframes.items():
                klines = await self.get_klines(symbol, tf_config['interval'], tf_config['candles'])
                
                if klines:
                    analysis = self.analyze_trend(klines)
                    result['timeframes'][tf_name] = analysis
                    
                    # Scoring для шорта
                    # DOWN = хорошо (+), UP = плохо (-), SIDEWAYS = нейтрально
                    if analysis['trend'] == 'DOWN':
                        tf_score = 5 + analysis['strength'] * 0.5  # 5-10
                        down_count += 1
                    elif analysis['trend'] == 'UP':
                        tf_score = 5 - analysis['strength'] * 0.5  # 0-5
                        up_count += 1
                    else:
                        tf_score = 5
                    
                    weighted_score += tf_score * tf_config['weight']
                    total_weight += tf_config['weight']
            
            # Финальный score
            if total_weight > 0:
                result['short_score'] = round(weighted_score / total_weight, 1)
            
            # Confluence
            if down_count >= 3:
                result['confluence'] = 'STRONG_SHORT'
                result['summary'] = f"✅ {down_count}/4 TF в даунтренде - сильный шорт"
            elif down_count >= 2:
                result['confluence'] = 'WEAK_SHORT'
                result['summary'] = f"🟡 {down_count}/4 TF в даунтренде - нормально"
            elif up_count >= 3:
                result['confluence'] = 'AVOID_SHORT'
                result['summary'] = f"⚠️ {up_count}/4 TF в аптренде - рискованно шортить"
            else:
                result['confluence'] = 'NEUTRAL'
                result['summary'] = f"⚪ Смешанные сигналы ({down_count} down, {up_count} up)"
            
            logger.info(f"⏱️ {symbol} MTF: {result['summary']} | Score: {result['short_score']}/10")
            
        except Exception as e:
            logger.error(f"MTF analysis error: {e}")
        
        return result


class VolumeProfileAnalyzer:
    """
    📊 VOLUME PROFILE ANALYZER
    
    Анализирует объём на разных ценовых уровнях.
    Высокий объём = сильная поддержка/сопротивление.
    """
    
    def __init__(self, rest_url: str = "https://contract.mexc.com"):
        self.rest_url = rest_url
        self.session = None
    
    async def analyze(self, symbol: str, current_price: float,
                     session: aiohttp.ClientSession = None) -> Dict:
        """
        Анализ Volume Profile.
        
        Returns:
            {
                'score': float (0-10),
                'nearest_support': float,
                'nearest_resistance': float,
                'high_volume_zones': list,
                'summary': str
            }
        """
        if session:
            self.session = session
        
        result = {
            'score': 5.0,
            'nearest_support': None,
            'nearest_resistance': None,
            'high_volume_zones': [],
            'summary': ''
        }
        
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            # Получаем 1h свечи за 24h
            url = f"{self.rest_url}/api/v1/contract/kline/{symbol}"
            params = {"interval": "Min60", "limit": 24}
            
            async with self.session.get(url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    return result
                
                data = await resp.json()
                if not data.get('success') or not data.get('data'):
                    return result
                
                klines = data['data']
            
            # Строим volume profile
            price_volumes = {}  # price_level -> total_volume
            
            for k in klines:
                if isinstance(k, dict):
                    high = float(k.get('high', k.get('h', 0)))
                    low = float(k.get('low', k.get('l', 0)))
                    volume = float(k.get('vol', k.get('v', 0)))
                elif isinstance(k, list) and len(k) >= 6:
                    high = float(k[2])
                    low = float(k[3])
                    volume = float(k[5])
                else:
                    continue
                
                # Распределяем объём по ценовым уровням
                price_range = high - low
                if price_range > 0:
                    steps = 5
                    step_vol = volume / steps
                    step_price = price_range / steps
                    
                    for i in range(steps):
                        level = round(low + step_price * i, 8)
                        price_volumes[level] = price_volumes.get(level, 0) + step_vol
            
            if not price_volumes:
                return result
            
            # Находим зоны высокого объёма
            avg_volume = sum(price_volumes.values()) / len(price_volumes)
            high_vol_zones = []
            
            for price, vol in sorted(price_volumes.items()):
                if vol > avg_volume * 1.5:
                    high_vol_zones.append({
                        'price': price,
                        'volume': vol,
                        'type': 'SUPPORT' if price < current_price else 'RESISTANCE'
                    })
            
            result['high_volume_zones'] = high_vol_zones[:5]  # Top 5
            
            # Ближайшие уровни
            supports = [z['price'] for z in high_vol_zones if z['type'] == 'SUPPORT']
            resistances = [z['price'] for z in high_vol_zones if z['type'] == 'RESISTANCE']
            
            if supports:
                result['nearest_support'] = max(supports)  # Ближайший снизу
            if resistances:
                result['nearest_resistance'] = min(resistances)  # Ближайший сверху
            
            # Score для шорта
            # Больше сопротивлений выше = плохо (цена может отскочить)
            # Мало поддержек ниже = хорошо (цена легко упадёт)
            support_count = len(supports)
            resistance_count = len(resistances)
            
            if support_count > resistance_count:
                # Много поддержек ниже = плохо для шорта
                result['score'] = 4.0
                result['summary'] = f"⚠️ Много поддержек ({support_count}) - шорт рискован"
            elif resistance_count > support_count:
                # Много сопротивлений выше = хорошо для шорта
                result['score'] = 7.0
                result['summary'] = f"✅ Мало поддержек, много сопротивлений - хорошо для шорта"
            else:
                result['score'] = 5.5
                result['summary'] = "Нейтральный volume profile"
            
        except Exception as e:
            logger.error(f"Volume profile error: {e}")
        
        return result


class CrossPairAnalyzer:
    """
    🔗 CROSS-PAIR CORRELATION ANALYZER
    
    Проверяет корреляцию с похожими монетами.
    Если все мем-коины пампят = общий тренд, а не изолированный памп.
    """
    
    def __init__(self, rest_url: str = "https://contract.mexc.com"):
        self.rest_url = rest_url
        self.session = None
        
        # Группы коррелированных монет
        self.meme_coins = ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'MEME']
        self.ai_coins = ['FET', 'AGIX', 'OCEAN', 'RNDR', 'TAO']
        self.layer1 = ['ETH', 'SOL', 'AVAX', 'NEAR', 'APT', 'SUI']
    
    def get_coin_group(self, symbol: str) -> List[str]:
        """Определить группу монеты."""
        base = symbol.replace('_USDT', '').replace('USDT', '')
        
        if base in self.meme_coins:
            return [c for c in self.meme_coins if c != base]
        elif base in self.ai_coins:
            return [c for c in self.ai_coins if c != base]
        elif base in self.layer1:
            return [c for c in self.layer1 if c != base]
        
        return []
    
    async def analyze(self, symbol: str, session: aiohttp.ClientSession = None) -> Dict:
        """
        Анализ корреляции с похожими монетами.
        
        Returns:
            {
                'score': float (0-10),
                'correlation': str ('ISOLATED', 'SECTOR_PUMP', 'SECTOR_DUMP'),
                'related_coins': list,
                'summary': str
            }
        """
        if session:
            self.session = session
        
        result = {
            'score': 5.0,
            'correlation': 'UNKNOWN',
            'related_coins': [],
            'summary': ''
        }
        
        try:
            group = self.get_coin_group(symbol)
            if not group:
                result['correlation'] = 'NO_GROUP'
                result['summary'] = "Монета не в известной группе"
                return result
            
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            # Получаем тикеры для группы
            url = f"{self.rest_url}/api/v1/contract/ticker"
            
            pumping = 0
            dumping = 0
            checked = []
            
            for coin in group[:5]:  # Проверяем до 5 монет
                coin_symbol = f"{coin}_USDT"
                
                try:
                    async with self.session.get(url, params={"symbol": coin_symbol}, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get('success') and data.get('data'):
                                change = float(data['data'].get('riseFallRate', 0)) * 100
                                
                                checked.append({'symbol': coin, 'change': change})
                                
                                if change >= 5:
                                    pumping += 1
                                elif change <= -5:
                                    dumping += 1
                except:
                    continue
            
            result['related_coins'] = checked
            
            # Определяем корреляцию
            if pumping >= 3:
                result['correlation'] = 'SECTOR_PUMP'
                result['score'] = 3.0  # Плохо для шорта - весь сектор пампит
                result['summary'] = f"⚠️ Сектор пампит ({pumping}/{len(checked)}) - рискованно шортить"
            elif dumping >= 3:
                result['correlation'] = 'SECTOR_DUMP'
                result['score'] = 8.0  # Хорошо для шорта - весь сектор дампит
                result['summary'] = f"✅ Сектор дампит ({dumping}/{len(checked)}) - хорошо для шорта"
            else:
                result['correlation'] = 'ISOLATED'
                result['score'] = 6.0  # Нейтрально - изолированное движение
                result['summary'] = f"Изолированное движение (не секторное)"
            
        except Exception as e:
            logger.error(f"Cross-pair analysis error: {e}")
        
        return result


# Глобальные экземпляры
_mtf_analyzer = None
_volume_analyzer = None
_cross_pair_analyzer = None

def get_mtf_analyzer() -> MultiTimeframeAnalyzer:
    global _mtf_analyzer
    if _mtf_analyzer is None:
        _mtf_analyzer = MultiTimeframeAnalyzer()
    return _mtf_analyzer

def get_volume_analyzer() -> VolumeProfileAnalyzer:
    global _volume_analyzer
    if _volume_analyzer is None:
        _volume_analyzer = VolumeProfileAnalyzer()
    return _volume_analyzer

def get_cross_pair_analyzer() -> CrossPairAnalyzer:
    global _cross_pair_analyzer
    if _cross_pair_analyzer is None:
        _cross_pair_analyzer = CrossPairAnalyzer()
    return _cross_pair_analyzer
