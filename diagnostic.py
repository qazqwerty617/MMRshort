"""
Диагностический скрипт - проверка данных от MEXC
"""
import asyncio
import websockets
import json
import time

async def test_mexc_connection():
    """Тест подключения к MEXC и вывод сырых данных"""
    
    ws_url = "wss://contract.mexc.com/edge"
    
    print("🔌 Подключаемся к MEXC WebSocket...")
    
    try:
        async with websockets.connect(ws_url) as ws:
            print("✅ Подключились!")
            
            # Подписываемся на BTC_USDT
            subscribe_msg = {
                "method": "sub.ticker",
                "param": {
                    "symbol": "BTC_USDT"
                }
            }
            
            await ws.send(json.dumps(subscribe_msg))
            print(f"📡 Подписались на BTC_USDT")
            
            # Получаем первые 10 сообщений
            print("\n" + "="*80)
            print("СЫРЫЕ ДАННЫЕ ОТ MEXC (первые 10 сообщений):")
            print("="*80 + "\n")
            
            count = 0
            while count < 10:
                message = await ws.recv()
                data = json.loads(message)
                
                # Показываем структуру данных
                if "channel" in data and "ticker" in data["channel"]:
                    count += 1
                    print(f"\n--- Сообщение #{count} ---")
                    print(f"Symbol: {data.get('symbol')}")
                    print(f"Timestamp: {data.get('ts')}")
                    print(f"Channel: {data.get('channel')}")
                    
                    if "data" in data:
                        price_data = data["data"]
                        print(f"\nДанные цены:")
                        print(f"  last (цена): {price_data.get('last')}")
                        print(f"  volume (объем): {price_data.get('volume')}")
                        print(f"  high24: {price_data.get('high24')}")
                        print(f"  low24: {price_data.get('low24')}")
                        print(f"\nПолная структура data:")
                        print(json.dumps(price_data, indent=2))
                elif "msg" == data.get("msg"):
                    print(f"Ping/Pong: {data}")
            
            print("\n" + "="*80)
            print("✅ Диагностика завершена!")
            print("="*80)
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(test_mexc_connection())
