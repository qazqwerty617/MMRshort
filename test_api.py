"""
Проверка доступности API анонсов MEXC
"""
import requests
import json

# Пробуем разные эндпоинты MEXC
endpoints = [
    "https://www.mexc.com/api/operation/announcements",
    "https://www.mexc.com/api/v1/announcement/list",
    "https://www.mexc.com/api/platform/spot/market-notification",
    "https://api3.mexc.com/api/v1/announcement",
    "https://www.mexc.com/ucenter/api/announcement/list",
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
}

for url in endpoints:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f"{url}")
        print(f"  Status: {r.status_code}")
        if r.ok and r.text:
            print(f"  Response: {r.text[:200]}")
        print()
    except Exception as e:
        print(f"{url} - Error: {e}")

# Попробуем Binance для сравнения
print("\n=== Binance Announcements ===")
r = requests.get(
    'https://www.binance.com/bapi/composite/v1/public/cms/article/list/query',
    params={'type': 1, 'pageNo': 1, 'pageSize': 5, 'catalogId': 48},
    headers=headers, timeout=10
)
if r.ok:
    data = r.json()
    catalogs = data.get('data', {}).get('catalogs', [])
    for cat in catalogs:
        for art in cat.get('articles', [])[:3]:
            print(f"Title: {art.get('title', '')[:70]}")
