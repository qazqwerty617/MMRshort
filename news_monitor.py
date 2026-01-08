"""
News Monitor - мониторинг новостей и sentiment анализ
Парсит публичные источники без API ключей
"""

import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import re
from logger import get_logger

logger = get_logger()


class NewsMonitor:
    """Мониторинг новостей из публичных источников"""
    
    def __init__(self):
        self.session = None
        
        # Negative keywords для FUD detection
        self.negative_keywords = [
            'hack', 'scam', 'rug', 'exploit', 'dump', 'crash', 'fraud',
            'ponzi', 'lawsuit', 'sec', 'regulation', 'ban', 'delisting',
            'хак', 'скам', 'мошенник', 'обман', 'слив'
        ]
        
        # Positive keywords
        self.positive_keywords = [
            'partnership', 'listing', 'launch', 'integration', 'update',
            'partnership', 'bull', 'moon', 'партнерство', 'запуск'
        ]
    
    async def check_twitter_sentiment(self, symbol: str) -> Dict:
        """
        Парсинг Twitter через nitter (публичный frontend)
        Nitter.net - бесплатный Twitter без API
        """
        try:
            clean_symbol = symbol.replace('_USDT', '').replace('USDT', '')
            
            # Используем nitter.net (публичный Twitter frontend)
            url = f"https://nitter.net/search?f=tweets&q=${clean_symbol}"
            
            async with self.session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return {'sentiment_score': 0, 'source': 'twitter', 'available': False}
                
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Ищем твиты
                tweets = soup.find_all('div', class_='tweet-content')[:20]  # Последние 20
                
                if not tweets:
                    return {'sentiment_score': 0, 'source': 'twitter', 'available': False}
                
                negative_count = 0
                positive_count = 0
                
                for tweet in tweets:
                    text = tweet.get_text().lower()
                    
                    # Проверяем на negative keywords
                    for keyword in self.negative_keywords:
                        if keyword in text:
                            negative_count += 1
                            break
                    
                    # Проверяем на positive keywords
                    for keyword in self.positive_keywords:
                        if keyword in text:
                            positive_count += 1
                            break
                
                # Рассчитываем sentiment score
                total = max(negative_count + positive_count, 1)
                sentiment_score = ((positive_count - negative_count) / total) * 10
                
                logger.info(f"🐦 Twitter: {clean_symbol} | Score: {sentiment_score:.1f} | Neg: {negative_count} Pos: {positive_count}")
                
                return {
                    'sentiment_score': sentiment_score,
                    'negative_mentions': negative_count,
                    'positive_mentions': positive_count,
                    'total_tweets': len(tweets),
                    'source': 'twitter',
                    'available': True
                }
                
        except Exception as e:
            logger.debug(f"Twitter check error: {e}")
            return {'sentiment_score': 0, 'source': 'twitter', 'available': False}
    
    async def check_google_news(self, symbol: str) -> Dict:
        """
        Парсинг Google News через RSS (публичный, без API)
        """
        try:
            clean_symbol = symbol.replace('_USDT', '').replace('USDT', '')
            
            # Google News RSS feed
            url = f"https://news.google.com/rss/search?q={clean_symbol}+crypto&hl=en-US&gl=US&ceid=US:en"
            
            async with self.session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return {'sentiment_score': 0, 'source': 'google', 'available': False}
                
                xml = await resp.text()
                
                # Простой парсинг XML
                articles = re.findall(r'<title>(.*?)</title>', xml)[:10]  # Первые 10
                
                if not articles:
                    return {'sentiment_score': 0, 'source': 'google', 'available': False}
                
                negative_count = 0
                positive_count = 0
                
                for article in articles:
                    text = article.lower()
                    
                    for keyword in self.negative_keywords:
                        if keyword in text:
                            negative_count += 1
                            break
                    
                    for keyword in self.positive_keywords:
                        if keyword in text:
                            positive_count += 1
                            break
                
                total = max(negative_count + positive_count, 1)
                sentiment_score = ((positive_count - negative_count) / total) * 10
                
                logger.info(f"📰 Google News: {clean_symbol} | Score: {sentiment_score:.1f} | Articles: {len(articles)}")
                
                return {
                    'sentiment_score': sentiment_score,
                    'negative_articles': negative_count,
                    'positive_articles': positive_count,
                    'total_articles': len(articles),
                    'source': 'google',
                    'available': True
                }
                
        except Exception as e:
            logger.debug(f"Google News check error: {e}")
            return {'sentiment_score': 0, 'source': 'google', 'available': False}
    
    async def check_coin_age(self, symbol: str) -> Optional[int]:
        """
        Проверка возраста монеты через CoinGecko (публичный API, без ключа)
        Возвращает возраст в днях
        """
        try:
            clean_symbol = symbol.replace('_USDT', '').replace('USDT', '')
            
            # CoinGecko публичный API
            url = f"https://api.coingecko.com/api/v3/coins/{clean_symbol.lower()}"
            
            async with self.session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                
                data = await resp.json()
                
                # Дата добавления на CoinGecko
                if 'genesis_date' in data and data['genesis_date']:
                    genesis = datetime.strptime(data['genesis_date'], '%Y-%m-%d')
                    age_days = (datetime.now() - genesis).days
                    return age_days
                
                return None
                
        except Exception as e:
            logger.debug(f"CoinGecko check error: {e}")
            return None
    
    async def analyze_symbol(self, symbol: str) -> Dict:
        """
        Полный анализ монеты: sentiment + возраст
        """
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        # Параллельные запросы
        twitter_task = self.check_twitter_sentiment(symbol)
        google_task = self.check_google_news(symbol)
        age_task = self.check_coin_age(symbol)
        
        twitter_result, google_result, coin_age = await asyncio.gather(
            twitter_task, google_task, age_task,
            return_exceptions=True
        )
        
        # Обработка ошибок
        if isinstance(twitter_result, Exception):
            twitter_result = {'sentiment_score': 0, 'available': False}
        if isinstance(google_result, Exception):
            google_result = {'sentiment_score': 0, 'available': False}
        if isinstance(coin_age, Exception):
            coin_age = None
        
        # Усредняем sentiment
        scores = []
        if twitter_result.get('available'):
            scores.append(twitter_result['sentiment_score'])
        if google_result.get('available'):
            scores.append(google_result['sentiment_score'])
        
        avg_sentiment = sum(scores) / len(scores) if scores else 0
        
        # Определяем категорию
        if avg_sentiment <= -5:
            sentiment_category = 'EXTREME_FUD'
            bonus_score = 3.0  # Отличный шорт!
        elif avg_sentiment <= -2:
            sentiment_category = 'NEGATIVE'
            bonus_score = 1.5
        elif avg_sentiment >= 5:
            sentiment_category = 'EXTREME_HYPE'
            bonus_score = -3.0  # Не шортить!
        elif avg_sentiment >= 2:
            sentiment_category = 'POSITIVE'
            bonus_score = -1.5
        else:
            sentiment_category = 'NEUTRAL'
            bonus_score = 0.0
        
        # Проверка новизны
        is_new_listing = coin_age is not None and coin_age < 7
        
        result = {
            'symbol': symbol,
            'sentiment_score': avg_sentiment,
            'sentiment_category': sentiment_category,
            'bonus_score': bonus_score,
            'twitter': twitter_result,
            'google': google_result,
            'coin_age_days': coin_age,
            'is_new_listing': is_new_listing,
            'timestamp': datetime.now()
        }
        
        logger.warning(f"📊 NEWS: {symbol} | Sentiment: {avg_sentiment:.1f} ({sentiment_category}) | Age: {coin_age or '?'}д | Bonus: {bonus_score:+.1f}")
        
        return result
    
    async def close(self):
        if self.session:
            await self.session.close()


# Singleton
_news_monitor = None

def get_news_monitor() -> NewsMonitor:
    global _news_monitor
    if _news_monitor is None:
        _news_monitor = NewsMonitor()
    return _news_monitor
