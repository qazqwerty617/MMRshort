"""
Telegram Channel Parser for MEXC Announcements
Парсит канал @MEXCofficialNews для получения анонсов листингов

Требует API credentials от https://my.telegram.org
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import json

try:
    from telethon import TelegramClient
    from telethon.tl.functions.messages import GetHistoryRequest
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

from logger import get_logger

logger = get_logger()


class TelegramListingParser:
    """Парсер листингов из Telegram канала MEXC"""
    
    # Каналы MEXC для мониторинга
    CHANNELS = [
        'MEXCOfficialNews',      # Официальные новости
        'MEXCEnglish',           # Английское сообщество  
        'mexc_announcements',    # Анонсы (если существует)
    ]
    
    def __init__(self, api_id: int = None, api_hash: str = None, session_name: str = "mexc_parser"):
        """
        Args:
            api_id: Telegram API ID (получить на my.telegram.org)
            api_hash: Telegram API Hash
            session_name: Имя файла сессии
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.client = None
        self.cache_file = Path("data/telegram_listings_cache.json")
        self._cache = {}
        self._load_cache()
        
    def _load_cache(self):
        """Загрузить кэш"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self._cache = json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки кэша: {e}")
            self._cache = {}
    
    def _save_cache(self):
        """Сохранить кэш"""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения кэша: {e}")
    
    async def connect(self) -> bool:
        """Подключиться к Telegram"""
        if not TELETHON_AVAILABLE:
            logger.error("Telethon не установлен!")
            return False
            
        if not self.api_id or not self.api_hash:
            logger.error("API credentials не указаны!")
            return False
        
        try:
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await self.client.start()
            logger.info("✅ Подключено к Telegram")
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к Telegram: {e}")
            return False
    
    async def disconnect(self):
        """Отключиться"""
        if self.client:
            await self.client.disconnect()
    
    async def get_channel_messages(self, channel: str, limit: int = 50) -> List[Dict]:
        """Получить последние сообщения из канала"""
        if not self.client:
            return []
        
        try:
            entity = await self.client.get_entity(channel)
            messages = await self.client(GetHistoryRequest(
                peer=entity,
                limit=limit,
                offset_date=None,
                offset_id=0,
                max_id=0,
                min_id=0,
                add_offset=0,
                hash=0
            ))
            
            result = []
            for msg in messages.messages:
                if msg.message:
                    result.append({
                        'id': msg.id,
                        'date': msg.date.isoformat() if msg.date else None,
                        'text': msg.message,
                    })
            return result
            
        except Exception as e:
            logger.error(f"Ошибка получения сообщений из {channel}: {e}")
            return []
    
    def parse_listing_announcement(self, text: str) -> Optional[Dict]:
        """Распарсить текст анонса листинга"""
        if not text:
            return None
        
        text_lower = text.lower()
        
        # Проверяем что это анонс листинга
        listing_keywords = [
            'will list', 'new listing', 'листинг', 'добавлен',
            'trading opens', 'торги открыты', 'perpetual', 'фьючерс'
        ]
        
        is_listing = any(kw in text_lower for kw in listing_keywords)
        if not is_listing:
            return None
        
        result = {
            'symbols': [],
            'trading_time': None,
            'type': 'spot',  # или 'futures'
            'raw_text': text[:500]
        }
        
        # Определяем тип (спот или фьючерсы)
        if 'perpetual' in text_lower or 'futures' in text_lower or 'фьючерс' in text_lower:
            result['type'] = 'futures'
        
        # Извлекаем символы монет
        # Паттерн 1: "List XXX (XXX)" 
        matches = re.findall(r'\b([A-Z]{2,10})(?:/USDT|USDT|\s*\()', text.upper())
        result['symbols'].extend(matches)
        
        # Паттерн 2: тикер в скобках
        matches = re.findall(r'\(([A-Z]{2,8})\)', text.upper())
        result['symbols'].extend(matches)
        
        # Паттерн 3: "XXX/USDT"
        matches = re.findall(r'\b([A-Z]{2,10})/USDT\b', text.upper())
        result['symbols'].extend(matches)
        
        result['symbols'] = list(set(result['symbols']))
        
        # Извлекаем время торгов
        # Паттерн: "2024-01-15 10:00 (UTC)"
        time_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', text)
        if time_match:
            result['trading_time'] = time_match.group(1)
        
        # Паттерн: "January 15, 2024 at 10:00"
        time_match = re.search(r'(\w+\s+\d{1,2},?\s+\d{4}\s+(?:at\s+)?\d{2}:\d{2})', text, re.IGNORECASE)
        if time_match and not result['trading_time']:
            result['trading_time'] = time_match.group(1)
        
        if result['symbols']:
            return result
        return None
    
    async def get_upcoming_listings(self, hours: int = 72) -> List[Dict]:
        """Получить предстоящие листинги за последние N часов анонсов"""
        if not self.client:
            # Возвращаем из кэша если нет подключения
            cached = self._cache.get('listings', [])
            return cached[:10]
        
        all_listings = []
        
        for channel in self.CHANNELS:
            try:
                messages = await self.get_channel_messages(channel, limit=100)
                
                for msg in messages:
                    parsed = self.parse_listing_announcement(msg['text'])
                    if parsed:
                        parsed['source'] = channel
                        parsed['message_date'] = msg['date']
                        parsed['message_id'] = msg['id']
                        all_listings.append(parsed)
                        
            except Exception as e:
                logger.error(f"Ошибка парсинга канала {channel}: {e}")
        
        # Убираем дубликаты по символам
        seen_symbols = set()
        unique_listings = []
        for listing in all_listings:
            key = tuple(sorted(listing['symbols']))
            if key not in seen_symbols:
                seen_symbols.add(key)
                unique_listings.append(listing)
        
        # Сохраняем в кэш
        self._cache['listings'] = unique_listings[:20]
        self._cache['updated_at'] = datetime.now().isoformat()
        self._save_cache()
        
        return unique_listings
    
    def get_cached_listings(self) -> List[Dict]:
        """Получить листинги из кэша (без подключения к Telegram)"""
        return self._cache.get('listings', [])


# Альтернативный парсер без Telethon (через публичный API t.me)
class SimpleTelegramParser:
    """Упрощенный парсер через t.me/s/ (публичный просмотр)"""
    
    def __init__(self):
        self.channels = ['MEXCOfficialNews']
        self.cache_file = Path("data/telegram_simple_cache.json")
        
    async def fetch_channel_preview(self, channel: str) -> List[Dict]:
        """Получить превью канала через публичный URL"""
        import aiohttp
        
        url = f"https://t.me/s/{channel}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        return self._parse_html(html)
        except Exception as e:
            logger.error(f"Ошибка получения превью канала: {e}")
        return []
    
    def _parse_html(self, html: str) -> List[Dict]:
        """Парсить HTML страницы t.me/s/"""
        messages = []
        
        # Ищем блоки сообщений - улучшенный паттерн
        pattern = r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>'
        matches = re.findall(pattern, html, re.DOTALL)
        
        for match in matches:
            # Убираем HTML теги
            text = re.sub(r'<[^>]+>', ' ', match)
            text = ' '.join(text.split())  # Убираем лишние пробелы
            
            if len(text) > 20:
                messages.append({
                    'text': text,
                    'date': datetime.now().isoformat()
                })
        
        return messages[:30]
    
    async def get_listings(self) -> List[Dict]:
        """Получить анонсы листингов"""
        all_messages = []
        
        for channel in self.channels:
            messages = await self.fetch_channel_preview(channel)
            all_messages.extend(messages)
        
        # Фильтруем только листинги
        listings = []
        parser = TelegramListingParser()
        
        for msg in all_messages:
            parsed = parser.parse_listing_announcement(msg['text'])
            if parsed:
                listings.append(parsed)
        
        return listings


async def test():
    """Тест парсера"""
    print("=== Testing SimpleTelegramParser ===")
    parser = SimpleTelegramParser()
    listings = await parser.get_listings()
    
    for l in listings[:5]:
        print(f"Symbols: {l['symbols']}")
        print(f"Type: {l['type']}")
        print(f"Time: {l.get('trading_time')}")
        print(f"Text: {l['raw_text'][:100]}...")
        print("---")


if __name__ == "__main__":
    asyncio.run(test())
