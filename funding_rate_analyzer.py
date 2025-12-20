"""
Funding Rate Analyzer - анализ funding rate для фьючерсов
"""

from typing import Dict, Optional
import aiohttp
from logger import get_logger

logger = get_logger()


class FundingRateAnalyzer:
    """Класс для анализа funding rate на фьючерсах"""
    
    def __init__(self, mexc_client):
        """
        Инициализация анализатора
        
        Args:
            mexc_client: Экземпляр MEXC клиента
        """
        self.mexc_client = mexc_client
        self.rest_url = mexc_client.rest_url
    
    async def get_funding_rate(self, symbol: str) -> Optional[Dict]:
        """
        Получить текущий funding rate для символа
        
        Args:
            symbol: Символ пары (например, BTC_USDT)
            
        Returns:
            {
                "funding_rate": float,  # Текущая ставка
                "next_funding_time": int,  # Время следующего funding
                "is_bullish": bool  # Положительная ставка = много лонгов
            }
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/v1/contract/funding_rate/{symbol}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            funding_data = data.get("data", {})
                            
                            funding_rate = float(funding_data.get("fundingRate", 0))
                            
                            return {
                                "funding_rate": funding_rate,
                                "funding_rate_pct": funding_rate * 100,  # В процентах
                                "next_funding_time": funding_data.get("nextFundingTime", 0),
                                "is_bullish": funding_rate > 0  # Положительный = много лонгов платят
                            }
        except Exception as e:
            logger.error(f"Ошибка получения funding rate для {symbol}: {e}")
        
        return None
    
    def calculate_funding_score(self, funding_data: Optional[Dict]) -> float:
        """
        Рассчитать score для шорта на основе funding rate
        Высокий положительный funding rate = хорошо для шорта
        
        Args:
            funding_data: Данные от get_funding_rate()
            
        Returns:
            Score от 0 до 10
        """
        if not funding_data:
            return 0.0
        
        funding_rate_pct = funding_data["funding_rate_pct"]
        
        # Если funding rate отрицательный (больше шортов) - не очень хорошо для шорта
        if funding_rate_pct < 0:
            return 0.0
        
        # Шкала scoring (положительный funding = хорошо для шорта):
        # 0.01% (0.0001) = 2.0 score
        # 0.05% (0.0005) = 5.0 score  
        # 0.10% (0.001) = 7.0 score
        # 0.20%+ (0.002+) = 10.0 score
        
        if funding_rate_pct >= 0.20:
            score = 10.0
        elif funding_rate_pct >= 0.10:
            score = 7.0 + ((funding_rate_pct - 0.10) / 0.10) * 3.0
        elif funding_rate_pct >= 0.05:
            score = 5.0 + ((funding_rate_pct - 0.05) / 0.05) * 2.0
        elif funding_rate_pct >= 0.01:
            score = 2.0 + ((funding_rate_pct - 0.01) / 0.04) * 3.0
        else:
            score = (funding_rate_pct / 0.01) * 2.0
        
        logger.debug(f"Funding rate: {funding_rate_pct:.4f}% → Score: {score:.1f}/10")
        
        return min(max(score, 0.0), 10.0)
    
    def format_funding_info(self, funding_data: Optional[Dict]) -> str:
        """
        Форматировать funding rate для отображения
        
        Args:
            funding_data: Данные funding rate
            
        Returns:
            Строка для вывода
        """
        if not funding_data:
            return "❓ Funding rate недоступен"
        
        rate_pct = funding_data["funding_rate_pct"]
        
        if rate_pct >= 0.10:
            emoji = "🔥"
            description = "очень высокий"
        elif rate_pct >= 0.05:
            emoji = "✅"
            description = "высокий"
        elif rate_pct > 0:
            emoji = "⚠️"
            description = "положительный"
        else:
            emoji = "❌"
            description = "отрицательный"
        
        return f"{emoji} Funding rate: {rate_pct:.4f}% ({description})"
