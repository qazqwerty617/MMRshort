"""
Listing Detector - автоматическое обнаружение новых фьючерсных контрактов
Мониторит MEXC API каждые 30 секунд
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from pathlib import Path
from typing import Set, Dict, Optional, Callable
from logger import get_logger

logger = get_logger()


class ListingDetector:
    """Детектор новых листингов фьючерсов на MEXC"""
    
    def __init__(self, on_new_listing: Optional[Callable] = None):
        """
        Args:
            on_new_listing: Callback функция при обнаружении нового листинга
                           Принимает (symbol: str, contract_data: dict)
        """
        self.api_url = "https://contract.mexc.com/api/v1/contract/detail"
        self.known_symbols: Set[str] = set()
        self.snapshot_file = Path("data/known_contracts.json")
        self.on_new_listing = on_new_listing
        self.check_interval = 30  # секунд
        self.running = False
        
        # Загружаем сохранённый снапшот
        self._load_snapshot()
    
    def _load_snapshot(self):
        """Загрузить известные контракты из файла"""
        try:
            if self.snapshot_file.exists():
                with open(self.snapshot_file, 'r') as f:
                    data = json.load(f)
                    self.known_symbols = set(data.get('symbols', []))
                    # Хранит когда впервые увидели контракт
                    self.first_seen = data.get('first_seen', {})
                    logger.info(f"📁 Загружено {len(self.known_symbols)} известных контрактов")
        except Exception as e:
            logger.error(f"Ошибка загрузки снапшота: {e}")
            self.known_symbols = set()
            self.first_seen = {}
    
    def _save_snapshot(self):
        """Сохранить известные контракты в файл"""
        try:
            self.snapshot_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.snapshot_file, 'w') as f:
                json.dump({
                    'symbols': list(self.known_symbols),
                    'first_seen': self.first_seen,
                    'updated_at': datetime.now().isoformat()
                }, f)
        except Exception as e:
            logger.error(f"Ошибка сохранения снапшота: {e}")
    
    async def fetch_contracts(self) -> Dict[str, dict]:
        """Получить все фьючерсные контракты с MEXC"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('success'):
                            contracts = {}
                            for contract in data.get('data', []):
                                symbol = contract.get('symbol', '')
                                if symbol:
                                    contracts[symbol] = {
                                        'symbol': symbol,
                                        'displayName': contract.get('displayName', ''),
                                        'baseCoin': contract.get('baseCoin', ''),
                                        'quoteCoin': contract.get('quoteCoin', ''),
                                        'maxLeverage': contract.get('maxLeverage', 0),
                                        'state': contract.get('state', 0),
                                    }
                            return contracts
        except Exception as e:
            logger.error(f"Ошибка получения контрактов: {e}")
        return {}
    
    async def check_new_listings(self) -> list:
        """Проверить наличие новых листингов"""
        contracts = await self.fetch_contracts()
        
        if not contracts:
            return []
        
        current_symbols = set(contracts.keys())
        new_listings = []
        
        # Записываем first_seen для всех новых
        now_iso = datetime.now().isoformat()
        for symbol in current_symbols:
            if symbol not in self.first_seen:
                self.first_seen[symbol] = now_iso
        
        # Находим новые символы
        if self.known_symbols:
            new_symbols = current_symbols - self.known_symbols
            
            for symbol in new_symbols:
                # Фильтруем только USDT-M контракты
                if symbol.endswith('_USDT'):
                    contract_data = contracts[symbol]
                    new_listings.append({
                        'symbol': symbol,
                        'data': contract_data,
                        'detected_at': datetime.now()
                    })
                    logger.warning(f"🚀 НОВЫЙ ЛИСТИНГ ОБНАРУЖЕН: {symbol}")
                    
                    # Вызываем callback
                    if self.on_new_listing:
                        try:
                            await self.on_new_listing(symbol, contract_data)
                        except Exception as e:
                            logger.error(f"Ошибка callback для {symbol}: {e}")
        else:
            logger.info(f"📊 Первый запуск: загружено {len(current_symbols)} контрактов")
        
        # Обновляем известные символы
        self.known_symbols = current_symbols
        self._save_snapshot()
        
        return new_listings
    
    async def run(self):
        """Запустить мониторинг листингов"""
        self.running = True
        logger.info(f"🔍 Listing Detector запущен (интервал: {self.check_interval}с)")
        
        while self.running:
            try:
                new_listings = await self.check_new_listings()
                
                if new_listings:
                    for listing in new_listings:
                        logger.warning(f"📢 Новый фьючерс: {listing['symbol']}")
                
            except Exception as e:
                logger.error(f"Ошибка проверки листингов: {e}")
            
            await asyncio.sleep(self.check_interval)
    
    def stop(self):
        """Остановить мониторинг"""
        self.running = False
        logger.info("🛑 Listing Detector остановлен")
    
    async def get_recent_listings(self, hours: int = 24) -> list:
        """Получить недавние листинги (для команды /listing)"""
        from datetime import timedelta
        
        contracts = await self.fetch_contracts()
        
        if not contracts:
            return []
        
        now = datetime.now()
        cutoff = now - timedelta(hours=hours)
        recent = []
        
        for symbol in contracts.keys():
            if not symbol.endswith('_USDT'):
                continue
            
            first_seen_str = self.first_seen.get(symbol)
            if not first_seen_str:
                continue
            
            try:
                first_seen = datetime.fromisoformat(first_seen_str)
            except:
                continue
            
            # Только добавленные за последние N часов
            if first_seen >= cutoff:
                contract = contracts[symbol]
                hours_ago = (now - first_seen).total_seconds() / 3600
                
                if hours_ago < 1:
                    time_str = f"{int(hours_ago * 60)} мин назад"
                else:
                    time_str = f"{hours_ago:.1f}ч назад"
                
                recent.append({
                    'symbol': symbol.replace('_USDT', ''),
                    'pair': symbol.replace('_', '/'),
                    'time_str': time_str,
                    'leverage': contract.get('maxLeverage', 0),
                    'hours_ago': hours_ago,
                    'first_seen': first_seen_str,
                    'source': 'mexc_futures'
                })
        
        # Сортируем по времени (новые первые)
        recent.sort(key=lambda x: x.get('hours_ago', 999))
        
        return recent[:15]


# Для обратной совместимости с mexc_scraper
class MexcScraper:
    """Обёртка для совместимости"""
    
    def __init__(self):
        self.detector = ListingDetector()
    
    async def get_new_listings(self):
        return await self.detector.get_recent_listings()
