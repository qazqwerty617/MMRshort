"""
Listing Tracker - отслеживание новых листингов
"""

from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
import asyncio
import aiohttp
from logger import get_logger

logger = get_logger()


class ListingTracker:
    """Класс для отслеживания новых листингов на биржах"""
    
    def __init__(self, mexc_client):
        """
        Инициализация трекера
        
        Args:
            mexc_client: MEXC клиент
        """
        self.mexc = mexc_client
        self.known_symbols: Set[str] = set()
        self.todays_listings: List[Dict] = []
        self.last_check = datetime.now()
    
    async def initialize(self):
        """Инициализировать список известных монет"""
        try:
            symbols = await self.mexc.get_all_symbols()
            if symbols:
                self.known_symbols = set(symbols)
                logger.info(f"Инициализировано {len(self.known_symbols)} известных пар")
        except Exception as e:
            logger.error(f"Ошибка инициализации listing tracker: {e}")
    
    async def check_for_new_listings(self) -> List[str]:
        """
        Проверить появление новых листингов
        
        Returns:
            Список новых символов
        """
        try:
            current_symbols = await self.mexc.get_all_symbols()
            if not current_symbols:
                return []
            
            current_set = set(current_symbols)
            new_symbols = current_set - self.known_symbols
            
            if new_symbols:
                logger.warning(f"🆕 Обнаружены новые листинги: {', '.join(new_symbols)}")
                
                # Добавляем в список листингов за сегодня
                for symbol in new_symbols:
                    listing_info = {
                        "symbol": symbol,
                        "detected_at": datetime.now(),
                        "exchange": "MEXC"
                    }
                    self.todays_listings.append(listing_info)
                
                # Обновляем набор известных символов
                self.known_symbols = current_set
                
                return list(new_symbols)
            
            return []
        
        except Exception as e:
            logger.error(f"Ошибка проверки новых листингов: {e}")
            return []
    
    def get_todays_listings(self) -> List[Dict]:
        """
        Получить список листингов за сегодня
        
        Returns:
            Список листингов
        """
        today = datetime.now().date()
        return [
            l for l in self.todays_listings
            if l["detected_at"].date() == today
        ]
    
    def clear_old_listings(self):
        """Очистить старые листинги (старше 24 часов)"""
        cutoff = datetime.now() - timedelta(days=1)
        self.todays_listings = [
            l for l in self.todays_listings
            if l["detected_at"] > cutoff
        ]


class CrossExchangeChecker:
    """Проверка наличия монеты на других биржах"""
    
    # API endpoints для проверки
    BINANCE_SPOT_API = "https://api.binance.com/api/v3/exchangeInfo"
    BINANCE_FUTURES_API = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    BYBIT_API = "https://api.bybit.com/v5/market/instruments-info"
    GATEIO_API = "https://api.gateio.ws/api/v4/spot/currency_pairs"
    
    def __init__(self):
        """Инициализация checker"""
        self.cache = {}
        self.cache_time = {}
    
    async def check_exchanges(self, symbol: str) -> Dict:
        """
        Проверить наличие монеты на других биржах
        
        Args:
            symbol: Символ для проверки (например, BTC_USDT)
            
        Returns:
            {
                "binance_spot": bool,
                "binance_futures": bool,
                "bybit": bool,
                "gateio": bool
            }
        """
        # Извлекаем базовую валюту (BTC из BTC_USDT)
        base_currency = symbol.split('_')[0]
        
        result = {
            "binance_spot": False,
            "binance_futures": False,
            "bybit": False,
            "gateio": False
        }
        
        # Проверяем каждую биржу
        result["binance_spot"] = await self._check_binance_spot(base_currency)
        result["binance_futures"] = await self._check_binance_futures(base_currency)
        result["bybit"] = await self._check_bybit(base_currency)
        result["gateio"] = await self._check_gateio(base_currency)
        
        return result
    
    async def _check_binance_spot(self, base: str) -> bool:
        """Проверить Binance Spot"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.BINANCE_SPOT_API, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        symbols = [s['symbol'] for s in data.get('symbols', [])]
                        # Проверяем BTC/USDT, BTC/BUSD и т.д.
                        return any(
                            f"{base}USDT" in symbols or
                            f"{base}BUSD" in symbols or
                            f"{base}BTC" in symbols
                        )
        except Exception as e:
            logger.debug(f"Ошибка проверки Binance Spot: {e}")
        return False
    
    async def _check_binance_futures(self, base: str) -> bool:
        """Проверить Binance Futures"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.BINANCE_FUTURES_API, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        symbols = [s['symbol'] for s in data.get('symbols', [])]
                        return f"{base}USDT" in symbols
        except Exception as e:
            logger.debug(f"Ошибка проверки Binance Futures: {e}")
        return False
    
    async def _check_bybit(self, base: str) -> bool:
        """Проверить Bybit"""
        try:
            async with aiohttp.ClientSession() as session:
                params = {"category": "linear"}
                async with session.get(self.BYBIT_API, params=params, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('retCode') == 0:
                            symbols = [s['symbol'] for s in data.get('result', {}).get('list', [])]
                            return f"{base}USDT" in symbols
        except Exception as e:
            logger.debug(f"Ошибка проверки Bybit: {e}")
        return False
    
    async def _check_gateio(self, base: str) -> bool:
        """Проверить Gate.io"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.GATEIO_API, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        symbols = [p['id'].upper() for p in data]
                        return f"{base}_USDT" in symbols
        except Exception as e:
            logger.debug(f"Ошибка проверки Gate.io: {e}")
        return False
    
    def format_exchange_status(self, status: Dict) -> str:
        """
        Форматировать статус для отображения
        
        Args:
            status: Результат check_exchanges()
            
        Returns:
            Форматированная строка
        """
        exchanges = []
        
        if status["binance_spot"]:
            exchanges.append("✅ Binance Spot")
        if status["binance_futures"]:
            exchanges.append("✅ Binance Futures")
        if status["bybit"]:
            exchanges.append("✅ Bybit")
        if status["gateio"]:
            exchanges.append("✅ Gate.io")
        
        if not exchanges:
            return "❌ Нет на других биржах (ЭКСКЛЮЗИВ!)"
        
        return "\n".join(exchanges)
