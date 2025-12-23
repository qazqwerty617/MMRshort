"""
Open Interest Analyzer - анализ изменений OI во время пампа
OI падает при росте цены = лонги закрываются = сильный сигнал на шорт
"""

import aiohttp
from typing import Dict, Optional
from logger import get_logger

logger = get_logger()


class OpenInterestAnalyzer:
    """Анализатор Open Interest для фьючерсов"""
    
    def __init__(self, rest_url: str = "https://contract.mexc.com"):
        self.rest_url = rest_url
        self.oi_history = {}  # symbol -> [(timestamp, oi_value), ...]
    
    async def get_open_interest(self, symbol: str, session: aiohttp.ClientSession = None) -> Optional[Dict]:
        """
        Получить текущий Open Interest для символа
        
        Returns:
            {
                'symbol': str,
                'open_interest': float,  # Контракты
                'open_interest_value': float,  # В USD
            }
        """
        try:
            close_session = False
            if not session:
                session = aiohttp.ClientSession()
                close_session = True
            
            url = f"{self.rest_url}/api/v1/contract/detail"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('success'):
                        for contract in data.get('data', []):
                            if contract.get('symbol') == symbol:
                                oi = float(contract.get('positionSize', 0))
                                # Сохраняем историю
                                if symbol not in self.oi_history:
                                    self.oi_history[symbol] = []
                                
                                import time
                                self.oi_history[symbol].append((time.time(), oi))
                                
                                # Храним только последние 100 записей
                                self.oi_history[symbol] = self.oi_history[symbol][-100:]
                                
                                if close_session:
                                    await session.close()
                                
                                return {
                                    'symbol': symbol,
                                    'open_interest': oi,
                                    'contract_size': float(contract.get('contractSize', 1)),
                                }
            
            if close_session:
                await session.close()
                
        except Exception as e:
            logger.error(f"Ошибка получения OI для {symbol}: {e}")
        
        return None
    
    def calculate_oi_change(self, symbol: str, lookback_minutes: int = 5) -> Optional[Dict]:
        """
        Рассчитать изменение OI за последние N минут
        
        Returns:
            {
                'oi_change_pct': float,  # Процент изменения
                'oi_trend': str,  # 'rising', 'falling', 'stable'
                'interpretation': str,  # Что это значит
            }
        """
        if symbol not in self.oi_history or len(self.oi_history[symbol]) < 2:
            return None
        
        import time
        cutoff = time.time() - (lookback_minutes * 60)
        
        recent = [x for x in self.oi_history[symbol] if x[0] >= cutoff]
        if len(recent) < 2:
            return None
        
        oi_start = recent[0][1]
        oi_end = recent[-1][1]
        
        if oi_start == 0:
            return None
        
        change_pct = ((oi_end - oi_start) / oi_start) * 100
        
        if change_pct > 5:
            trend = 'rising'
            interpretation = "🔺 OI растёт - новые лонги открываются (осторожно с шортом!)"
        elif change_pct < -5:
            trend = 'falling'
            interpretation = "🔻 OI падает - лонги закрываются (сильный сигнал на шорт!)"
        else:
            trend = 'stable'
            interpretation = "➡️ OI стабилен"
        
        return {
            'oi_change_pct': change_pct,
            'oi_trend': trend,
            'interpretation': interpretation,
            'oi_start': oi_start,
            'oi_end': oi_end,
        }
    
    def calculate_oi_score(self, oi_data: Optional[Dict], oi_change: Optional[Dict]) -> float:
        """
        Рассчитать скор OI для шорт сигнала (0-10)
        
        Высокий скор = OI падает (лонги закрываются) = хорошо для шорта
        """
        if not oi_change:
            return 5.0  # Нейтральный если нет данных
        
        change_pct = oi_change.get('oi_change_pct', 0)
        
        # OI падает - отлично для шорта
        if change_pct <= -20:
            return 10.0
        elif change_pct <= -10:
            return 9.0
        elif change_pct <= -5:
            return 8.0
        elif change_pct <= 0:
            return 6.0
        # OI растёт - плохо для шорта
        elif change_pct <= 5:
            return 4.0
        elif change_pct <= 10:
            return 2.0
        else:
            return 0.0  # OI сильно растёт - много новых лонгов!
    
    async def analyze(self, symbol: str, session: aiohttp.ClientSession = None) -> Dict:
        """
        Полный анализ OI для символа
        
        Returns:
            {
                'oi_data': dict,
                'oi_change': dict,
                'oi_score': float,
            }
        """
        oi_data = await self.get_open_interest(symbol, session)
        oi_change = self.calculate_oi_change(symbol)
        oi_score = self.calculate_oi_score(oi_data, oi_change)
        
        if oi_change:
            logger.info(f"📊 {symbol}: OI {oi_change['oi_trend']} ({oi_change['oi_change_pct']:+.1f}%) | Score: {oi_score:.1f}/10")
        
        return {
            'oi_data': oi_data,
            'oi_change': oi_change,
            'oi_score': oi_score,
        }
