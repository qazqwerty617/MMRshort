"""
Announcement Parser - Гибридный подход:
1. Мониторинг новых контрактов MEXC (уже реализовано)  
2. Парсинг Binance анонсов (косвенный индикатор - если Binance листит, MEXC часто тоже)
3. Отслеживание "первых минут" контракта на MEXC

Фактически: показываем "только что добавленные" контракты (< 24ч)
+ уведомляем в реальном времени при появлении нового
"""

import asyncio
import aiohttp
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from logger import get_logger

logger = get_logger()


class AnnouncementParser:
    """Парсер анонсов листингов с разных источников"""
    
    def __init__(self):
        self.binance_api = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        
    async def get_binance_new_listings(self) -> List[Dict]:
        """Получить новые листинги с Binance (как индикатор тренда)"""
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    'type': 1,
                    'pageNo': 1,
                    'pageSize': 20,
                    'catalogId': 48  # New Listings
                }
                async with session.get(self.binance_api, params=params, headers=self.headers, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        listings = []
                        
                        catalogs = data.get('data', {}).get('catalogs', [])
                        for cat in catalogs:
                            for article in cat.get('articles', []):
                                title = article.get('title', '')
                                code = article.get('code', '')
                                release_date = article.get('releaseDate')
                                
                                # Ищем символы монет в заголовке
                                # Паттерн: "Binance Will List XXX (XXX)" или "XXX/USDT"
                                symbols = self._extract_symbols(title)
                                
                                if symbols:
                                    listings.append({
                                        'source': 'binance',
                                        'title': title,
                                        'symbols': symbols,
                                        'date': release_date,
                                        'url': f"https://www.binance.com/en/support/announcement/{code}"
                                    })
                        
                        return listings[:10]
        except Exception as e:
            logger.error(f"Ошибка получения Binance анонсов: {e}")
        return []
    
    def _extract_symbols(self, title: str) -> List[str]:
        """Извлечь символы монет из заголовка"""
        symbols = []
        
        # Паттерн 1: "List XXX (XXX)" - название и тикер
        match = re.search(r'List\s+\w+\s*\((\w+)\)', title, re.IGNORECASE)
        if match:
            symbols.append(match.group(1).upper())
        
        # Паттерн 2: "XXX/USDT" или "XXXUSDT"
        matches = re.findall(r'\b([A-Z]{2,10})(?:/USDT|USDT)\b', title.upper())
        symbols.extend(matches)
        
        # Паттерн 3: просто тикер в скобках (XXX)
        matches = re.findall(r'\(([A-Z]{2,8})\)', title.upper())
        symbols.extend(matches)
        
        return list(set(symbols))
    
    async def check_mexc_has_futures(self, symbol: str) -> Optional[Dict]:
        """Проверить есть ли фьючерс на MEXC для данного символа"""
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://contract.mexc.com/api/v1/contract/detail"
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('success'):
                            for contract in data.get('data', []):
                                if contract.get('baseCoin', '').upper() == symbol.upper():
                                    return {
                                        'symbol': contract.get('symbol'),
                                        'baseCoin': contract.get('baseCoin'),
                                        'maxLeverage': contract.get('maxLeverage'),
                                        'exists': True
                                    }
        except Exception as e:
            logger.error(f"Ошибка проверки MEXC: {e}")
        return None


async def test():
    parser = AnnouncementParser()
    
    print("=== Binance New Listings ===")
    listings = await parser.get_binance_new_listings()
    for l in listings[:5]:
        print(f"Title: {l['title'][:60]}...")
        print(f"Symbols: {l['symbols']}")
        print(f"Date: {l['date']}")
        print()
        
        # Проверяем есть ли на MEXC
        for sym in l['symbols']:
            mexc = await parser.check_mexc_has_futures(sym)
            if mexc:
                print(f"  ✅ MEXC Futures: {mexc['symbol']} (x{mexc['maxLeverage']})")
            else:
                print(f"  ❌ MEXC Futures: {sym} - НЕТ")
        print("---")


if __name__ == "__main__":
    asyncio.run(test())
