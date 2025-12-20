"""
MEXC New Listings Scraper
Парсит анонсы о новых листингах с сайта поддержки MEXC
"""

import aiohttp
import re
from datetime import datetime
from typing import List, Dict, Optional
from logger import get_logger

logger = get_logger()

class MexcScraper:
    """Парсер новых листингов MEXC"""
    
    def __init__(self):
        # Используем API анонсов
        self.api_url = "https://www.mexc.com/api/platform/spot/market/announcement/list"
        # Полные заголовки как у реального браузера
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.mexc.com/support/articles/category/36000025",
            "Origin": "https://www.mexc.com",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }
        
    async def get_new_listings(self) -> List[Dict]:
        """
        Получить список будущих листингов
        """
        listings = []
        
        try:
            async with aiohttp.ClientSession() as session:
                # Запрашиваем анонсы (тип 1 = New Listing)
                params = {"type": 1, "pageNum": 1, "pageSize": 10}
                async with session.get(self.api_url, params=params, headers=self.headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        articles = data.get('data', {}).get('result', [])
                        
                        for article in articles:
                            title = article.get('title', '')
                            # Ищем паттерн "Will List Token (SYMBOL)"
                            match = re.search(r'\(([A-Z0-9]+)\)', title)
                            if match:
                                symbol = match.group(1)
                                release_time = article.get('releaseTime', 0) # timestamp ms
                                
                                dt = datetime.fromtimestamp(release_time / 1000)
                                time_str = dt.strftime("%d.%m (%H:%M)")
                                
                                # Проверяем, будущее ли это время
                                if dt > datetime.now():
                                    listings.append({
                                        "symbol": symbol,
                                        "pair": f"{symbol}/USDT",
                                        "time_str": time_str,
                                        "timestamp": release_time,
                                        "title": title
                                    })
        
        except Exception as e:
            logger.error(f"Ошибка парсинга MEXC: {e}")
            
        return listings
