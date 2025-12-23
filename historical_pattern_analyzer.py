"""
Historical Pattern Analyzer - анализ поведения монеты при прошлых пампах
Сохраняет данные в БД и обучается на реальных результатах
"""

import json
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from pathlib import Path
from logger import get_logger

logger = get_logger()


class HistoricalPatternAnalyzer:
    """Анализатор исторических паттернов с сохранением в файл"""
    
    # Паттерны поведения после пампа
    PATTERN_V_SHAPE = "V_SHAPE"      # Быстро восстанавливается (опасно шортить!)
    PATTERN_L_SHAPE = "L_SHAPE"      # Остаётся внизу (хорошо для шорта)
    PATTERN_SLOW_BLEED = "SLOW_BLEED"  # Медленно сливается (лучший для шорта)
    PATTERN_UNKNOWN = "UNKNOWN"
    
    def __init__(self, data_file: str = "data/coin_patterns.json"):
        self.data_file = Path(data_file)
        self.coin_patterns: Dict[str, dict] = {}
        self.pump_history: Dict[str, list] = {}
        
        self._load_data()
    
    def _load_data(self):
        """Загрузить данные из файла"""
        try:
            if self.data_file.exists():
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.coin_patterns = data.get('patterns', {})
                    self.pump_history = data.get('history', {})
                    logger.info(f"📂 Загружено {len(self.coin_patterns)} паттернов монет")
        except Exception as e:
            logger.error(f"Ошибка загрузки паттернов: {e}")
    
    def _save_data(self):
        """Сохранить данные в файл"""
        try:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'patterns': self.coin_patterns,
                    'history': self.pump_history,
                    'updated_at': datetime.now().isoformat()
                }, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Ошибка сохранения паттернов: {e}")
    
    async def record_signal_result(self, signal_data: dict):
        """
        Записать результат сигнала для обучения
        Вызывается из SignalTracker через callback
        """
        symbol = signal_data.get('symbol', '')
        if not symbol:
            return
        
        peak_price = signal_data.get('peak_price', 0)
        price_5m = signal_data.get('price_5m', 0)
        price_15m = signal_data.get('price_15m', 0)
        price_60m = signal_data.get('price_60m', 0)
        
        if not all([peak_price, price_5m, price_15m, price_60m]):
            return
        
        # Рассчитываем падение от пика
        drop_5m = ((peak_price - price_5m) / peak_price) * 100
        drop_15m = ((peak_price - price_15m) / peak_price) * 100
        drop_60m = ((peak_price - price_60m) / peak_price) * 100
        
        # Определяем паттерн
        if drop_60m < 3 or (drop_15m > drop_60m and drop_60m < 5):
            # Цена вернулась - V-shape
            pattern = self.PATTERN_V_SHAPE
        elif drop_60m > drop_15m > drop_5m and drop_60m > 10:
            # Продолжает падать - slow bleed
            pattern = self.PATTERN_SLOW_BLEED
        else:
            # Упала и осталась - L-shape
            pattern = self.PATTERN_L_SHAPE
        
        # Сохраняем в историю
        if symbol not in self.pump_history:
            self.pump_history[symbol] = []
        
        self.pump_history[symbol].append({
            'timestamp': datetime.now().isoformat(),
            'pump_pct': signal_data.get('pump_pct', 0),
            'drop_5m': drop_5m,
            'drop_15m': drop_15m,
            'drop_60m': drop_60m,
            'pattern': pattern,
            'result': signal_data.get('result', 'unknown'),
            'profit_pct': signal_data.get('profit_pct', 0),
        })
        
        # Обновляем общий паттерн монеты
        self._update_coin_pattern(symbol)
        self._save_data()
        
        logger.info(f"📝 {symbol}: Записан паттерн {pattern} (drop: 5m={drop_5m:.1f}%, 15m={drop_15m:.1f}%, 60m={drop_60m:.1f}%)")
    
    def _update_coin_pattern(self, symbol: str):
        """Обновить общий паттерн монеты на основе истории"""
        if symbol not in self.pump_history:
            return
        
        history = self.pump_history[symbol][-10:]  # Последние 10 пампов
        
        if not history:
            return
        
        # Считаем какой паттерн чаще
        patterns = [h['pattern'] for h in history]
        pattern_counts = {
            self.PATTERN_V_SHAPE: patterns.count(self.PATTERN_V_SHAPE),
            self.PATTERN_L_SHAPE: patterns.count(self.PATTERN_L_SHAPE),
            self.PATTERN_SLOW_BLEED: patterns.count(self.PATTERN_SLOW_BLEED),
        }
        
        dominant_pattern = max(pattern_counts, key=pattern_counts.get)
        confidence = pattern_counts[dominant_pattern] / len(patterns)
        
        # Считаем win rate
        results = [h.get('result') for h in history]
        wins = results.count('win')
        win_rate = wins / len(results) if results else 0
        
        self.coin_patterns[symbol] = {
            'pattern': dominant_pattern,
            'confidence': confidence,
            'pump_count': len(history),
            'win_rate': win_rate,
            'updated_at': datetime.now().isoformat()
        }
    
    def get_coin_pattern(self, symbol: str) -> Dict:
        """Получить паттерн поведения монеты"""
        if symbol not in self.coin_patterns:
            return {
                'pattern': self.PATTERN_UNKNOWN,
                'confidence': 0,
                'pump_count': 0,
                'win_rate': 0,
                'short_recommendation': "Нет истории - осторожно",
            }
        
        data = self.coin_patterns[symbol]
        pattern = data['pattern']
        
        if pattern == self.PATTERN_V_SHAPE:
            recommendation = "⚠️ ОПАСНО ШОРТИТЬ - обычно быстро восстанавливается!"
        elif pattern == self.PATTERN_SLOW_BLEED:
            recommendation = "✅ ЛУЧШИЙ ДЛЯ ШОРТА - обычно медленно сливается"
        elif pattern == self.PATTERN_L_SHAPE:
            recommendation = "✅ ХОРОШ ДЛЯ ШОРТА - обычно остаётся внизу"
        else:
            recommendation = "Недостаточно данных"
        
        return {
            'pattern': pattern,
            'confidence': data.get('confidence', 0),
            'pump_count': data.get('pump_count', 0),
            'win_rate': data.get('win_rate', 0),
            'short_recommendation': recommendation,
        }
    
    def calculate_pattern_score(self, symbol: str) -> float:
        """Рассчитать скор паттерна для шорт сигнала (0-10)"""
        pattern_data = self.get_coin_pattern(symbol)
        pattern = pattern_data['pattern']
        confidence = pattern_data['confidence']
        
        if pattern == self.PATTERN_UNKNOWN:
            return 5.0  # Нейтральный
        
        base_scores = {
            self.PATTERN_SLOW_BLEED: 10.0,
            self.PATTERN_L_SHAPE: 8.0,
            self.PATTERN_V_SHAPE: 2.0,
        }
        
        base = base_scores.get(pattern, 5.0)
        score = base * confidence + 5.0 * (1 - confidence)
        
        return min(10.0, max(0.0, score))
    
    def analyze(self, symbol: str) -> Dict:
        """Полный анализ паттерна монеты"""
        pattern_data = self.get_coin_pattern(symbol)
        pattern_score = self.calculate_pattern_score(symbol)
        
        if pattern_data['pattern'] != self.PATTERN_UNKNOWN:
            logger.info(f"📜 {symbol}: Паттерн {pattern_data['pattern']} (уверенность: {pattern_data['confidence']:.0%}, WR: {pattern_data['win_rate']:.0%}) | Score: {pattern_score:.1f}/10")
        
        return {
            **pattern_data,
            'pattern_score': pattern_score,
        }
