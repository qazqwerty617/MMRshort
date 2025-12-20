"""
Exchange Checker - проверка наличия монеты на других биржах
Поддерживает: Binance, Bybit, Gate.io
"""

import aiohttp
import asyncio
from typing import Dict, List, Optional
from logger import get_logger

logger = get_logger()

class ExchangeChecker:
    """Проверка наличия монеты на биржах"""
    
    def __init__(self):
        self.sessions = {}
        
    async def check_binance(self, symbol: str) -> Optional[str]:
        """Проверить наличие на Binance и вернуть ссылку"""
        base_coin = symbol.split('_')[0].upper()
        clean_pair = f"{base_coin}USDT"
        
        try:
            async with aiohttp.ClientSession() as session:
                # Проверка Spot
                url = "https://api.binance.com/api/v3/exchangeInfo"
                async with session.get(url, params={"symbol": clean_pair}) as resp:
                    if resp.status == 200:
                        return f"https://www.binance.com/en/trade/{base_coin}_USDT"
                        
                # Проверка Futures
                url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for s in data.get('symbols', []):
                            if s['symbol'] == clean_pair:
                                return f"https://www.binance.com/en/futures/{base_coin}USDT"
        except Exception as e:
            logger.error(f"Ошибка Binance check для {symbol}: {e}")
        return None

    async def check_bybit(self, symbol: str) -> Optional[str]:
        """Проверить наличие на Bybit и вернуть ссылку"""
        base_coin = symbol.split('_')[0].upper()
        
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.bybit.com/v5/market/tickers"
                async with session.get(url, params={"category": "spot", "symbol": f"{base_coin}USDT"}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('retCode') == 0 and data.get('result', {}).get('list'):
                            return f"https://www.bybit.com/trade/spot/{base_coin}/USDT"
        except Exception as e:
            logger.error(f"Ошибка Bybit check для {symbol}: {e}")
        return None

    async def check_gate(self, symbol: str) -> Optional[str]:
        """Проверить наличие на Gate.io и вернуть ссылку"""
        base_coin = symbol.split('_')[0].upper()
        
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.gateio.ws/api/v4/spot/currency_pairs"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for pair in data:
                            if pair['id'] == f"{base_coin}_USDT":
                                return f"https://www.gate.io/trade/{base_coin}_USDT"
        except Exception as e:
            logger.error(f"Ошибка Gate.io check для {symbol}: {e}")
        return None

    async def check_all_exchanges(self, symbol: str) -> Dict[str, Optional[str]]:
        """Проверить на всех биржах параллельно"""
        results = {}
        
        # Запускаем проверки параллельно
        tasks = [
            self.check_binance(symbol),
            self.check_bybit(symbol),
            self.check_gate(symbol)
        ]
        
        check_results = await asyncio.gather(*tasks)
        
        results['Binance'] = check_results[0]
        results['Bybit'] = check_results[1]
        results['Gate'] = check_results[2]
        
        return results
