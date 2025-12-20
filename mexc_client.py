"""
MEXC Client - клиент для работы с MEXC API (WebSocket и REST)
"""

import asyncio
import websockets
import json
import time
from typing import Dict, List, Callable, Optional
import aiohttp
from logger import get_logger

logger = get_logger()


class MEXCClient:
    """Клиент для MEXC фьючерсов"""
    
    def __init__(self, config: Dict):
        """
        Инициализация клиента
        
        Args:
            config: Конфигурация из config.yaml секции 'mexc'
        """
        self.config = config
        self.ws_url = config['ws_endpoint']
        self.rest_url = config['rest_endpoint']
        self.ping_interval = config['ping_interval']
        
        self.ws = None
        self.running = False
        self.callbacks: Dict[str, List[Callable]] = {}
        
        # Кэш данных
        self.current_prices: Dict[str, float] = {}
        self.available_pairs: List[str] = []
    
    async def connect(self):
        """Подключиться к WebSocket"""
        try:
            self.ws = await websockets.connect(self.ws_url)
            self.running = True
            logger.info(f"Подключились к MEXC WebSocket: {self.ws_url}")
            
            # Запускаем пинг и обработку сообщений
            asyncio.create_task(self._ping_loop())
            asyncio.create_task(self._message_loop())
            
        except Exception as e:
            logger.error(f"Ошибка подключения к MEXC WebSocket: {e}")
            raise
    
    async def disconnect(self):
        """Отключиться от WebSocket"""
        self.running = False
        if self.ws:
            await self.ws.close()
            logger.info("Отключились от MEXC WebSocket")
    
    async def _ping_loop(self):
        """Цикл отправки ping сообщений"""
        while self.running:
            try:
                await asyncio.sleep(self.ping_interval)
                if self.ws:
                    await self.ws.send(json.dumps({"method": "ping"}))
                    logger.debug("Отправлен ping")
            except Exception as e:
                logger.error(f"Ошибка отправки ping: {e}")
                break
    
    async def _message_loop(self):
        """Цикл обработки входящих сообщений"""
        while self.running:
            try:
                message = await self.ws.recv()
                await self._handle_message(json.loads(message))
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket соединение закрыто")
                break
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения: {e}")
    
    async def _handle_message(self, data: Dict):
        """
        Обработать входящее сообщение
        
        Args:
            data: Распарсенный JSON
        """
        # Обработка pong
        if data.get("msg") == "pong":
            logger.debug("Получен pong")
            return
        
        # Обработка данных тикера
        if "channel" in data and "ticker" in data["channel"]:
            symbol = data.get("symbol")
            if symbol and "data" in data:
                price_data = data["data"]
                
                # Обновляем текущую цену
                if "last" in price_data:
                    self.current_prices[symbol] = float(price_data["last"])
                
                # Вызываем подписанные колбэки
                await self._trigger_callbacks("ticker", {
                    "symbol": symbol,
                    "price": float(price_data.get("last", 0)),
                    "volume": float(price_data.get("volume", 0)),
                    "timestamp": data.get("ts", int(time.time() * 1000))
                })
        
        # Обработка kline данных
        elif "channel" in data and "kline" in data["channel"]:
            symbol = data.get("symbol")
            if symbol and "data" in data:
                kline_data = data["data"]
                
                await self._trigger_callbacks("kline", {
                    "symbol": symbol,
                    "open": float(kline_data.get("o", 0)),
                    "high": float(kline_data.get("h", 0)),
                    "low": float(kline_data.get("l", 0)),
                    "close": float(kline_data.get("c", 0)),
                    "volume": float(kline_data.get("v", 0)),
                    "timestamp": kline_data.get("t", 0)
                })
    
    async def subscribe_ticker(self, symbol: str):
        """
        Подписаться на тикер монеты
        
        Args:
            symbol: Символ пары (например, BTC_USDT)
        """
        if not self.ws:
            logger.error("WebSocket не подключен")
            return
        
        subscribe_msg = {
            "method": "sub.ticker",
            "param": {
                "symbol": symbol
            }
        }
        
        await self.ws.send(json.dumps(subscribe_msg))
        logger.info(f"Подписались на тикер: {symbol}")
    
    async def subscribe_kline(self, symbol: str, interval: str = "Min1"):
        """
        Подписаться на свечи (kline)
        
        Args:
            symbol: Символ пары
            interval: Интервал (Min1, Min5, Min15, Hour1, Day1, etc)
        """
        if not self.ws:
            logger.error("WebSocket не подключен")
            return
        
        subscribe_msg = {
            "method": "sub.kline",
            "param": {
                "symbol": symbol,
                "interval": interval
            }
        }
        
        await self.ws.send(json.dumps(subscribe_msg))
        logger.info(f"Подписались на kline: {symbol} ({interval})")
    
    def on(self, event: str, callback: Callable):
        """
        Зарегистрировать колбэк для события
        
        Args:
            event: Тип события ('ticker', 'kline', etc)
            callback: Async функция-обработчик
        """
        if event not in self.callbacks:
            self.callbacks[event] = []
        self.callbacks[event].append(callback)
        logger.debug(f"Добавлен колбэк для события: {event}")
    
    async def _trigger_callbacks(self, event: str, data: Dict):
        """Вызвать все колбэки для события"""
        if event in self.callbacks:
            for callback in self.callbacks[event]:
                try:
                    await callback(data)
                except Exception as e:
                    logger.error(f"Ошибка в колбэке {event}: {e}")
    
    async def get_all_symbols(self) -> List[str]:
        """
        Получить список всех доступных фьючерсных пар
        
        Returns:
            Список символов
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/v1/contract/detail"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            symbols = [item["symbol"] for item in data.get("data", [])]
                            self.available_pairs = symbols
                            logger.info(f"Получено {len(symbols)} фьючерсных пар")
                            return symbols
        except Exception as e:
            logger.error(f"Ошибка получения списка пар: {e}")
        
        return []
    
    async def get_orderbook(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """
        Получить ордербук для пары
        
        Args:
            symbol: Символ пары
            limit: Глубина ордербука
            
        Returns:
            {"bids": [...], "asks": [...]}
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/v1/contract/depth/{symbol}"
                params = {"limit": limit}
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            return data.get("data")
        except Exception as e:
            logger.error(f"Ошибка получения ордербука {symbol}: {e}")
        
        return None
    
    async def get_klines(self, symbol: str, interval: str = "Min1", limit: int = 100) -> List[Dict]:
        """
        Получить исторические свечи
        
        Args:
            symbol: Символ пары
            interval: Интервал свечи
            limit: Количество свечей
            
        Returns:
            Список свечей
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.rest_url}/api/v1/contract/kline/{symbol}"
                params = {"interval": interval, "limit": limit}
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            klines = data.get("data", [])
                            # Конвертируем в удобный формат
                            return [{
                                "timestamp": k["time"],
                                "open": float(k["open"]),
                                "high": float(k["high"]),
                                "low": float(k["low"]),
                                "close": float(k["close"]),
                                "volume": float(k["vol"])
                            } for k in klines]
        except Exception as e:
            logger.error(f"Ошибка получения klines {symbol}: {e}")
        
        return []
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Получить текущую цену из кэша
        
        Args:
            symbol: Символ пары
            
        Returns:
            Цена или None
        """
        return self.current_prices.get(symbol)
