"""
DEX Price Analyzer - проверка цены на DexScreener
Если цена MEXC > цена DEX = сигнал к шорту
"""

import aiohttp
from typing import Optional, Dict
from logger import get_logger

logger = get_logger()


class DexAnalyzer:
    """Анализатор цен на DEX"""
    
    def __init__(self):
        self.dex_api = "https://api.dexscreener.com/latest/dex"
    
    async def get_dex_price(self, symbol: str) -> Optional[Dict]:
        """
        Получить цену монеты на DEX
        
        Args:
            symbol: Символ пары (например, BTC_USDT -> преобразуем в BTC)
            
        Returns:
            {
                "price": float,
                "dex_name": str,
                "liquidity": float,
                "volume_24h": float
            }
        """
        # Извлекаем базовую монету (BTC_USDT -> BTC)
        base_token = symbol.split('_')[0]
        
        # Пропускаем стейблкоины и фиатные пары
        skip_tokens = ['USDT', 'USDC', 'BUSD', 'DAI', 'USD', 'EUR', 'GBP']
        if base_token in skip_tokens:
            return None
        
        try:
            async with aiohttp.ClientSession() as session:
                # Поиск по токену
                url = f"{self.dex_api}/search/?q={base_token}"
                
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        pairs = data.get('pairs', [])
                        if not pairs:
                            logger.debug(f"DEX: {base_token} не найден")
                            return None
                        
                        # Берем пару с наибольшей ликвидностью
                        best_pair = max(pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0))
                        
                        if not best_pair:
                            return None
                        
                        price_usd = float(best_pair.get('priceUsd', 0))
                        if price_usd == 0:
                            return None
                        
                        result = {
                            "price": price_usd,
                            "dex_name": best_pair.get('dexId', 'unknown'),
                            "liquidity": float(best_pair.get('liquidity', {}).get('usd', 0) or 0),
                            "volume_24h": float(best_pair.get('volume', {}).get('h24', 0) or 0),
                            "chain": best_pair.get('chainId', 'unknown'),
                            "pair_address": best_pair.get('pairAddress', '')
                        }
                        
                        logger.info(f"✅ DEX {base_token}: ${price_usd:.6f} на {result['dex_name']} (ликв: ${result['liquidity']:,.0f})")
                        return result
        
        except asyncio.TimeoutError:
            logger.warning(f"DEX: Timeout для {base_token}")
        except Exception as e:
            logger.error(f"DEX ошибка для {base_token}: {e}")
        
        return None
    
    def calculate_cex_dex_spread(self, cex_price: float, dex_price: float) -> Dict:
        """
        Рассчитать спред между CEX и DEX
        
        Args:
            cex_price: Цена на CEX (MEXC)
            dex_price: Цена на DEX
            
        Returns:
            {
                "spread_pct": float,  # Процент разницы
                "is_overvalued_on_cex": bool,  # CEX цена выше DEX = переоценена
                "spread_score": float  # Score 0-10 для сигнала
            }
        """
        if dex_price == 0:
            return {"spread_pct": 0, "is_overvalued_on_cex": False, "spread_score": 0}
        
        # Разница в процентах (положительная = CEX дороже)
        spread_pct = ((cex_price - dex_price) / dex_price) * 100
        
        is_overvalued = spread_pct > 0  # CEX > DEX
        
        # Score: чем больше спред, тем лучше для шорта
        # 0-2% = 0 score
        # 2-5% = 5 score
        # 5-10% = 8 score
        # 10%+ = 10 score
        if spread_pct < 2:
            score = 0
        elif spread_pct < 5:
            score = ((spread_pct - 2) / 3) * 5
        elif spread_pct < 10:
            score = 5 + ((spread_pct - 5) / 5) * 3
        else:
            score = 10
        
        # Отрицательный спред (CEX дешевле DEX) = 0 score
        if not is_overvalued:
            score = 0
        
        return {
            "spread_pct": spread_pct,
            "is_overvalued_on_cex": is_overvalued,
            "spread_score": min(score, 10.0)
        }
