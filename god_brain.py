"""
🧠 GOD BRAIN v1.0 - Ultimate Learning System

ФИЛОСОФИЯ:
Бот УЧИТСЯ на каждом сигнале. Запоминает как ведёт себя каждая монета.
Через 100 сигналов он будет ТОЧНЕЕ человека.

ФУНКЦИИ:
1. ПАМЯТЬ: Хранит каждую отработку в SQLite (вечно)
2. LEARNING: Анализирует паттерны - какие условия = WIN/LOSS
3. PREDICTION: Предсказывает успех нового сигнала на основе истории
4. ADAPTATION: Автоматически корректирует веса факторов для каждой монеты
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging
import math

logger = logging.getLogger(__name__)


class GodBrain:
    """
    🧠 ULTIMATE LEARNING ENGINE
    
    Помнит ВСЁ. Учится на каждой сделке. Становится умнее с каждым сигналом.
    """
    
    def __init__(self, db_path: str = "data/god_brain.db"):
        self.db_path = db_path
        self._init_database()
        
        # Кэш профилей для быстрого доступа
        self.coin_memory = {}  # symbol -> CoinMemory
        self._load_all_profiles()
    
    def _init_database(self):
        """Создать таблицы для хранения памяти."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица всех сигналов с полной детализацией
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signal_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                
                -- Условия входа
                pump_pct REAL NOT NULL,
                pump_speed_minutes REAL NOT NULL,
                entry_price REAL NOT NULL,
                peak_price REAL NOT NULL,
                start_price REAL NOT NULL,
                
                -- Все scores на момент сигнала
                god_eye_score REAL DEFAULT 5.0,
                dominator_score REAL DEFAULT 5.0,
                orderbook_score REAL DEFAULT 5.0,
                oi_score REAL DEFAULT 5.0,
                funding_score REAL DEFAULT 5.0,
                btc_score REAL DEFAULT 5.0,
                liq_score REAL DEFAULT 5.0,
                combined_score REAL DEFAULT 5.0,
                
                -- TP/SL уровни
                sl_price REAL,
                tp1_price REAL,
                tp2_price REAL,
                tp3_price REAL,
                
                -- РЕЗУЛЬТАТЫ (заполняются позже)
                price_5m REAL,
                price_15m REAL,
                price_30m REAL,
                price_1h REAL,
                price_4h REAL,
                
                hit_tp1 BOOLEAN DEFAULT FALSE,
                hit_tp2 BOOLEAN DEFAULT FALSE,
                hit_tp3 BOOLEAN DEFAULT FALSE,
                hit_sl BOOLEAN DEFAULT FALSE,
                
                max_profit_pct REAL,
                max_drawdown_pct REAL,
                final_result TEXT,  -- 'WIN_TP1', 'WIN_TP2', 'WIN_TP3', 'LOSS_SL', 'BREAKEVEN', 'TIMEOUT'
                
                -- Метаданные для обучения
                market_condition TEXT,  -- 'BULL', 'BEAR', 'SIDEWAYS'
                btc_trend TEXT,  -- 'UP', 'DOWN', 'FLAT'
                was_liquidation_sweep BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # Таблица профилей монет (агрегированная статистика)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS coin_intelligence (
                symbol TEXT PRIMARY KEY,
                
                -- Общая статистика
                total_signals INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0.5,
                
                -- Средние значения
                avg_pump_pct REAL DEFAULT 0,
                avg_dump_pct REAL DEFAULT 0,
                avg_dump_time_minutes REAL DEFAULT 0,
                avg_max_profit REAL DEFAULT 0,
                avg_max_drawdown REAL DEFAULT 0,
                
                -- TP статистика
                tp1_hit_rate REAL DEFAULT 0,
                tp2_hit_rate REAL DEFAULT 0,
                tp3_hit_rate REAL DEFAULT 0,
                sl_hit_rate REAL DEFAULT 0,
                
                -- Оптимальные условия для этой монеты
                best_pump_range_min REAL DEFAULT 10,
                best_pump_range_max REAL DEFAULT 50,
                best_combined_score_min REAL DEFAULT 6,
                
                -- Множители для корректировки (обучаемые)
                tp_multiplier REAL DEFAULT 1.0,
                sl_multiplier REAL DEFAULT 1.0,
                confidence_adjustment REAL DEFAULT 0,  -- -2 to +2
                
                -- Рекомендации
                recommended_action TEXT DEFAULT 'TRADE',  -- 'TRADE', 'AVOID', 'CAUTION'
                notes TEXT,
                
                last_updated TIMESTAMP
            )
        ''')
        
        # Индексы
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_memory_symbol ON signal_memory(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_memory_created ON signal_memory(created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_memory_result ON signal_memory(final_result)')
        
        conn.commit()
        conn.close()
        logger.info(f"🧠 GOD BRAIN инициализирован: {self.db_path}")
    
    def _load_all_profiles(self):
        """Загрузить все профили в память."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM coin_intelligence')
        rows = cursor.fetchall()
        
        for row in rows:
            # Преобразуем в словарь
            columns = [d[0] for d in cursor.description]
            profile = dict(zip(columns, row))
            self.coin_memory[profile['symbol']] = profile
        
        conn.close()
        logger.info(f"🧠 Загружено {len(self.coin_memory)} профилей монет")
    
    def record_signal(self, signal_data: Dict) -> int:
        """
        Записать новый сигнал в память.
        
        Args:
            signal_data: {
                'symbol': str,
                'pump_pct': float,
                'pump_speed_minutes': float,
                'entry_price': float,
                'peak_price': float,
                'start_price': float,
                'god_eye_score': float,
                'dominator_score': float,
                'orderbook_score': float,
                'oi_score': float,
                'funding_score': float,
                'btc_score': float,
                'liq_score': float,
                'combined_score': float,
                'sl_price': float,
                'tp1_price': float,
                'tp2_price': float,
                'tp3_price': float,
            }
        
        Returns:
            signal_id в базе для последующего update
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO signal_memory (
                symbol, created_at, pump_pct, pump_speed_minutes,
                entry_price, peak_price, start_price,
                god_eye_score, dominator_score, orderbook_score,
                oi_score, funding_score, btc_score, liq_score, combined_score,
                sl_price, tp1_price, tp2_price, tp3_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal_data['symbol'],
            datetime.now(),
            signal_data.get('pump_pct', 0),
            signal_data.get('pump_speed_minutes', 0),
            signal_data['entry_price'],
            signal_data.get('peak_price', signal_data['entry_price']),
            signal_data.get('start_price', signal_data['entry_price']),
            signal_data.get('god_eye_score', 5.0),
            signal_data.get('dominator_score', 5.0),
            signal_data.get('orderbook_score', 5.0),
            signal_data.get('oi_score', 5.0),
            signal_data.get('funding_score', 5.0),
            signal_data.get('btc_score', 5.0),
            signal_data.get('liq_score', 5.0),
            signal_data.get('combined_score', 5.0),
            signal_data.get('sl_price'),
            signal_data.get('tp1_price'),
            signal_data.get('tp2_price'),
            signal_data.get('tp3_price')
        ))
        
        signal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"🧠 Сигнал #{signal_id} записан: {signal_data['symbol']}")
        return signal_id
    
    def update_signal_outcome(self, signal_id: int, outcome_data: Dict):
        """
        Обновить результат сигнала после отработки.
        
        Args:
            signal_id: ID сигнала
            outcome_data: {
                'price_5m': float,
                'price_15m': float,
                'price_30m': float,
                'price_1h': float,
                'price_4h': float,
                'hit_tp1': bool,
                'hit_tp2': bool,
                'hit_tp3': bool,
                'hit_sl': bool,
                'max_profit_pct': float,
                'max_drawdown_pct': float,
                'final_result': str,  # 'WIN_TP1', 'WIN_TP2', 'WIN_TP3', 'LOSS_SL', 'BREAKEVEN', 'TIMEOUT'
            }
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE signal_memory SET
                price_5m = ?, price_15m = ?, price_30m = ?, price_1h = ?, price_4h = ?,
                hit_tp1 = ?, hit_tp2 = ?, hit_tp3 = ?, hit_sl = ?,
                max_profit_pct = ?, max_drawdown_pct = ?, final_result = ?
            WHERE id = ?
        ''', (
            outcome_data.get('price_5m'),
            outcome_data.get('price_15m'),
            outcome_data.get('price_30m'),
            outcome_data.get('price_1h'),
            outcome_data.get('price_4h'),
            outcome_data.get('hit_tp1', False),
            outcome_data.get('hit_tp2', False),
            outcome_data.get('hit_tp3', False),
            outcome_data.get('hit_sl', False),
            outcome_data.get('max_profit_pct', 0),
            outcome_data.get('max_drawdown_pct', 0),
            outcome_data.get('final_result', 'UNKNOWN')
        ))
        
        conn.commit()
        
        # Получаем символ для обновления профиля
        cursor.execute('SELECT symbol FROM signal_memory WHERE id = ?', (signal_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            symbol = row[0]
            self._update_coin_intelligence(symbol)
            logger.info(f"🧠 Результат сигнала #{signal_id} записан: {outcome_data.get('final_result')}")
    
    def _update_coin_intelligence(self, symbol: str):
        """Пересчитать интеллект для конкретной монеты на основе всей истории."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Получаем все сигналы по монете
        cursor.execute('''
            SELECT * FROM signal_memory 
            WHERE symbol = ? AND final_result IS NOT NULL
            ORDER BY created_at DESC
        ''', (symbol,))
        
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        signals = [dict(zip(columns, row)) for row in rows]
        
        if not signals:
            conn.close()
            return
        
        # Считаем статистику
        total = len(signals)
        wins = len([s for s in signals if s['final_result'] and s['final_result'].startswith('WIN')])
        losses = len([s for s in signals if s['final_result'] == 'LOSS_SL'])
        
        tp1_hits = len([s for s in signals if s['hit_tp1']])
        tp2_hits = len([s for s in signals if s['hit_tp2']])
        tp3_hits = len([s for s in signals if s['hit_tp3']])
        sl_hits = len([s for s in signals if s['hit_sl']])
        
        # Средние значения
        avg_pump = sum(s['pump_pct'] or 0 for s in signals) / total if total else 0
        avg_max_profit = sum(s['max_profit_pct'] or 0 for s in signals) / total if total else 0
        avg_max_dd = sum(s['max_drawdown_pct'] or 0 for s in signals) / total if total else 0
        
        # Win rate
        win_rate = wins / total if total > 0 else 0.5
        
        # TP hit rates
        tp1_rate = tp1_hits / total if total > 0 else 0
        tp2_rate = tp2_hits / total if total > 0 else 0
        tp3_rate = tp3_hits / total if total > 0 else 0
        sl_rate = sl_hits / total if total > 0 else 0
        
        # Определяем рекомендацию
        if win_rate >= 0.7 and total >= 5:
            recommended = 'TRADE'  # Отличная монета
            confidence_adj = 1.0
        elif win_rate >= 0.5:
            recommended = 'TRADE'
            confidence_adj = 0
        elif win_rate >= 0.3:
            recommended = 'CAUTION'  # Осторожно
            confidence_adj = -1.0
        else:
            recommended = 'AVOID'  # Избегать
            confidence_adj = -2.0
        
        # Корректировка TP/SL на основе истории
        # Если часто бьёт SL до TP1 - нужен шире SL
        if sl_rate > 0.5 and tp1_rate < 0.3:
            sl_mult = 1.2  # Шире стоп
            tp_mult = 0.8  # Ближе тейки
        elif tp3_rate > 0.5:
            sl_mult = 1.0
            tp_mult = 1.2  # Можно ставить дальше
        else:
            sl_mult = 1.0
            tp_mult = 1.0
        
        # Записываем в базу
        cursor.execute('''
            INSERT OR REPLACE INTO coin_intelligence (
                symbol, total_signals, wins, losses, win_rate,
                avg_pump_pct, avg_max_profit, avg_max_drawdown,
                tp1_hit_rate, tp2_hit_rate, tp3_hit_rate, sl_hit_rate,
                tp_multiplier, sl_multiplier, confidence_adjustment,
                recommended_action, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            symbol, total, wins, losses, win_rate,
            avg_pump, avg_max_profit, avg_max_dd,
            tp1_rate, tp2_rate, tp3_rate, sl_rate,
            tp_mult, sl_mult, confidence_adj,
            recommended, datetime.now()
        ))
        
        conn.commit()
        conn.close()
        
        # Обновляем кэш
        self.coin_memory[symbol] = {
            'symbol': symbol,
            'total_signals': total,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'tp1_hit_rate': tp1_rate,
            'tp2_hit_rate': tp2_rate,
            'tp3_hit_rate': tp3_rate,
            'sl_hit_rate': sl_rate,
            'tp_multiplier': tp_mult,
            'sl_multiplier': sl_mult,
            'confidence_adjustment': confidence_adj,
            'recommended_action': recommended
        }
        
        logger.info(f"🧠 {symbol}: Обновлён профиль | WR: {win_rate*100:.0f}% | TP1: {tp1_rate*100:.0f}% | Action: {recommended}")
    
    def get_coin_intelligence(self, symbol: str) -> Dict:
        """
        Получить интеллект по монете.
        
        Returns:
            {
                'win_rate': float (0-1),
                'tp_multiplier': float,
                'sl_multiplier': float,
                'confidence_adjustment': float (-2 to +2),
                'recommended_action': str,
                'total_signals': int,
                'tp1_hit_rate': float,
                ...
            }
        """
        if symbol in self.coin_memory:
            return self.coin_memory[symbol]
        
        # Дефолт для новой монеты
        return {
            'symbol': symbol,
            'total_signals': 0,
            'win_rate': 0.5,
            'tp_multiplier': 1.0,
            'sl_multiplier': 1.0,
            'confidence_adjustment': 0,
            'recommended_action': 'TRADE',
            'tp1_hit_rate': 0,
            'tp2_hit_rate': 0,
            'tp3_hit_rate': 0,
            'sl_hit_rate': 0
        }
    
    def predict_success(self, symbol: str, combined_score: float, pump_pct: float) -> Dict:
        """
        Предсказать вероятность успеха сигнала на основе истории.
        
        Returns:
            {
                'predicted_win_rate': float (0-1),
                'confidence': str ('HIGH', 'MEDIUM', 'LOW', 'NO_DATA'),
                'adjustment': float (-2 to +2),
                'recommendation': str,
                'reasoning': str
            }
        """
        intel = self.get_coin_intelligence(symbol)
        
        # Нет данных
        if intel['total_signals'] == 0:
            return {
                'predicted_win_rate': 0.5,
                'confidence': 'NO_DATA',
                'adjustment': 0,
                'recommendation': 'TRADE',
                'reasoning': 'Новая монета - нет исторических данных'
            }
        
        total = intel['total_signals']
        base_win_rate = intel['win_rate']
        
        # Confidence based on sample size
        if total >= 20:
            confidence = 'HIGH'
        elif total >= 10:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'
        
        # Корректировка на основе текущих условий
        # Если combined_score выше среднего - увеличиваем прогноз
        adjusted_rate = base_win_rate
        
        if combined_score >= 8:
            adjusted_rate = min(1.0, base_win_rate + 0.15)
        elif combined_score >= 7:
            adjusted_rate = min(1.0, base_win_rate + 0.1)
        elif combined_score <= 4:
            adjusted_rate = max(0, base_win_rate - 0.15)
        
        # Формируем рекомендацию
        if adjusted_rate >= 0.7 and confidence in ['HIGH', 'MEDIUM']:
            recommendation = 'STRONG_TRADE'
            reasoning = f"✅ Историческая WR {base_win_rate*100:.0f}% + хороший score = сильный сигнал"
        elif adjusted_rate >= 0.5:
            recommendation = 'TRADE'
            reasoning = f"Нормальная WR {base_win_rate*100:.0f}%"
        elif adjusted_rate >= 0.3:
            recommendation = 'CAUTION'
            reasoning = f"⚠️ Низкая WR {base_win_rate*100:.0f}% - осторожно"
        else:
            recommendation = 'AVOID'
            reasoning = f"❌ Плохая история ({base_win_rate*100:.0f}% WR) - лучше пропустить"
        
        return {
            'predicted_win_rate': adjusted_rate,
            'confidence': confidence,
            'adjustment': intel['confidence_adjustment'],
            'recommendation': recommendation,
            'reasoning': reasoning,
            'historical_signals': total,
            'tp_multiplier': intel['tp_multiplier'],
            'sl_multiplier': intel['sl_multiplier']
        }
    
    def get_adjusted_score(self, symbol: str, base_score: float) -> float:
        """
        Скорректировать combined_score на основе истории монеты.
        
        Returns:
            Скорректированный score (0-10)
        """
        intel = self.get_coin_intelligence(symbol)
        adjustment = intel.get('confidence_adjustment', 0)
        
        adjusted = base_score + adjustment
        return max(0, min(10, adjusted))
    
    def get_adjusted_tps(self, symbol: str, tps: List[float], entry_price: float) -> List[float]:
        """
        Скорректировать TP уровни на основе истории монеты.
        
        Если монета исторически хорошо отрабатывает - ставим дальше.
        Если плохо - ставим ближе.
        """
        intel = self.get_coin_intelligence(symbol)
        multiplier = intel.get('tp_multiplier', 1.0)
        
        if multiplier == 1.0:
            return tps
        
        # Корректируем расстояние от entry до TP
        adjusted_tps = []
        for tp in tps:
            distance = entry_price - tp  # Положительное для шорта
            new_distance = distance * multiplier
            adjusted_tps.append(entry_price - new_distance)
        
        return adjusted_tps
    
    def get_statistics_summary(self) -> Dict:
        """Получить сводную статистику по всем монетам."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                COUNT(*) as total_signals,
                SUM(CASE WHEN final_result LIKE 'WIN%' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN final_result = 'LOSS_SL' THEN 1 ELSE 0 END) as losses,
                AVG(max_profit_pct) as avg_profit,
                COUNT(DISTINCT symbol) as unique_coins
            FROM signal_memory
            WHERE final_result IS NOT NULL
        ''')
        
        row = cursor.fetchone()
        conn.close()
        
        if not row or row[0] == 0:
            return {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0, 'avg_profit': 0}
        
        total, wins, losses, avg_profit, unique_coins = row
        
        return {
            'total': total,
            'wins': wins or 0,
            'losses': losses or 0,
            'win_rate': (wins / total * 100) if total > 0 else 0,
            'avg_profit': avg_profit or 0,
            'unique_coins': unique_coins or 0,
            'coins_in_memory': len(self.coin_memory)
        }
    
    # ═══════════════════════════════════════════════════════════════
    # 🔥 ADVANCED LEARNING FEATURES v2.0
    # ═══════════════════════════════════════════════════════════════
    
    def find_similar_signals(self, symbol: str, pump_pct: float, 
                            combined_score: float, limit: int = 10) -> List[Dict]:
        """
        🔍 Найти похожие сигналы из истории для сравнения.
        
        Ищет сигналы с похожими условиями и показывает как они отработали.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Ищем сигналы с похожими параметрами
        cursor.execute('''
            SELECT * FROM signal_memory
            WHERE symbol = ? 
            AND final_result IS NOT NULL
            AND ABS(pump_pct - ?) < 10
            AND ABS(combined_score - ?) < 2
            ORDER BY created_at DESC
            LIMIT ?
        ''', (symbol, pump_pct, combined_score, limit))
        
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        conn.close()
        
        return [dict(zip(columns, row)) for row in rows]
    
    def get_weighted_win_rate(self, symbol: str, decay_factor: float = 0.95) -> float:
        """
        📉 Win Rate с временным затуханием.
        Недавние сигналы важнее старых.
        
        decay_factor = 0.95 означает что каждый более старый сигнал 
        весит на 5% меньше предыдущего.
        
        Returns:
            Weighted win rate (0-1)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT final_result, created_at
            FROM signal_memory
            WHERE symbol = ? AND final_result IS NOT NULL
            ORDER BY created_at DESC
        ''', (symbol,))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return 0.5
        
        weighted_wins = 0
        total_weight = 0
        
        for i, (result, _) in enumerate(rows):
            weight = decay_factor ** i  # Чем старше, тем меньше вес
            is_win = 1 if result and result.startswith('WIN') else 0
            
            weighted_wins += is_win * weight
            total_weight += weight
        
        return weighted_wins / total_weight if total_weight > 0 else 0.5
    
    def get_streak_info(self, symbol: str) -> Dict:
        """
        🔥 Отслеживание серий побед/поражений.
        
        Returns:
            {
                'current_streak': int (+ для побед, - для поражений),
                'streak_type': 'WIN' или 'LOSS',
                'max_win_streak': int,
                'max_loss_streak': int,
                'is_hot': bool (3+ побед подряд),
                'is_cold': bool (3+ поражений подряд)
            }
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT final_result
            FROM signal_memory
            WHERE symbol = ? AND final_result IS NOT NULL
            ORDER BY created_at DESC
        ''', (symbol,))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return {
                'current_streak': 0, 'streak_type': 'NONE',
                'max_win_streak': 0, 'max_loss_streak': 0,
                'is_hot': False, 'is_cold': False
            }
        
        results = [r[0] for r in rows]
        
        # Текущая серия
        current_streak = 0
        first_type = 'WIN' if results[0] and results[0].startswith('WIN') else 'LOSS'
        
        for r in results:
            is_win = r and r.startswith('WIN')
            if (first_type == 'WIN' and is_win) or (first_type == 'LOSS' and not is_win):
                current_streak += 1
            else:
                break
        
        if first_type == 'LOSS':
            current_streak = -current_streak
        
        # Максимальные серии
        max_win = 0
        max_loss = 0
        current_win = 0
        current_loss = 0
        
        for r in results:
            if r and r.startswith('WIN'):
                current_win += 1
                current_loss = 0
                max_win = max(max_win, current_win)
            else:
                current_loss += 1
                current_win = 0
                max_loss = max(max_loss, current_loss)
        
        return {
            'current_streak': current_streak,
            'streak_type': first_type,
            'max_win_streak': max_win,
            'max_loss_streak': max_loss,
            'is_hot': current_streak >= 3,
            'is_cold': current_streak <= -3
        }
    
    def get_optimal_conditions(self, symbol: str) -> Dict:
        """
        🎯 Найти оптимальные условия входа для монеты.
        
        Анализирует, при каких параметрах сигналы работали лучше всего.
        
        Returns:
            {
                'optimal_pump_range': (min, max),
                'optimal_score_min': float,
                'best_time_hours': list,  # Часы UTC когда работает лучше
                'winning_factor_weights': dict  # Какие факторы важнее
            }
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT pump_pct, combined_score, god_eye_score, dominator_score,
                   orderbook_score, oi_score, funding_score, btc_score, liq_score,
                   final_result, created_at
            FROM signal_memory
            WHERE symbol = ? AND final_result IS NOT NULL
        ''', (symbol,))
        
        rows = cursor.fetchall()
        conn.close()
        
        if len(rows) < 5:
            return {
                'optimal_pump_range': (10, 50),
                'optimal_score_min': 6.0,
                'best_time_hours': [],
                'winning_factor_weights': {},
                'has_data': False
            }
        
        wins = []
        losses = []
        
        for row in rows:
            (pump, combined, god_eye, dominator, ob, oi, funding, btc, liq, 
             result, created) = row
            
            data = {
                'pump_pct': pump or 0,
                'combined_score': combined or 5,
                'god_eye_score': god_eye or 5,
                'dominator_score': dominator or 5,
                'orderbook_score': ob or 5,
                'oi_score': oi or 5,
                'funding_score': funding or 5,
                'btc_score': btc or 5,
                'liq_score': liq or 5,
                'hour': datetime.fromisoformat(created).hour if created else 0
            }
            
            if result and result.startswith('WIN'):
                wins.append(data)
            else:
                losses.append(data)
        
        if not wins:
            return {'has_data': False}
        
        # Optimal pump range
        win_pumps = [w['pump_pct'] for w in wins]
        optimal_pump_min = min(win_pumps) if win_pumps else 10
        optimal_pump_max = max(win_pumps) if win_pumps else 50
        
        # Optimal score minimum
        win_scores = [w['combined_score'] for w in wins]
        optimal_score_min = sum(win_scores) / len(win_scores) - 1 if win_scores else 6
        
        # Best hours
        win_hours = [w['hour'] for w in wins]
        hour_counts = defaultdict(int)
        for h in win_hours:
            hour_counts[h] += 1
        best_hours = sorted(hour_counts.keys(), key=lambda h: hour_counts[h], reverse=True)[:3]
        
        # Factor importance (simple comparison of means)
        factors = ['god_eye_score', 'dominator_score', 'orderbook_score', 
                   'oi_score', 'funding_score', 'btc_score', 'liq_score']
        factor_weights = {}
        
        for f in factors:
            win_avg = sum(w[f] for w in wins) / len(wins) if wins else 5
            loss_avg = sum(l[f] for l in losses) / len(losses) if losses else 5
            # Чем больше разница, тем важнее фактор
            importance = win_avg - loss_avg
            factor_weights[f] = round(importance, 2)
        
        # Сортируем по важности
        sorted_factors = sorted(factor_weights.items(), key=lambda x: abs(x[1]), reverse=True)
        
        return {
            'optimal_pump_range': (round(optimal_pump_min, 1), round(optimal_pump_max, 1)),
            'optimal_score_min': round(optimal_score_min, 1),
            'best_time_hours': best_hours,
            'winning_factor_weights': dict(sorted_factors),
            'total_wins': len(wins),
            'total_losses': len(losses),
            'has_data': True
        }
    
    def get_smart_prediction(self, symbol: str, pump_pct: float, 
                            combined_score: float, hour: int = None) -> Dict:
        """
        🧠 SMART PREDICTION - Максимально умный прогноз.
        
        Комбинирует ВСЕ факторы:
        - Историческая WR
        - Weighted WR (с затуханием)
        - Похожие сигналы
        - Текущая серия
        - Оптимальные условия
        
        Returns:
            {
                'final_score': float (0-10),
                'prediction': str ('STRONG_BUY', 'BUY', 'NEUTRAL', 'AVOID'),
                'confidence': float (0-100%),
                'factors': dict,
                'reasoning': list[str]
            }
        """
        if hour is None:
            hour = datetime.now().hour
        
        reasoning = []
        
        # 1. Базовый интеллект
        intel = self.get_coin_intelligence(symbol)
        base_wr = intel.get('win_rate', 0.5)
        total_signals = intel.get('total_signals', 0)
        
        # 2. Weighted WR
        weighted_wr = self.get_weighted_win_rate(symbol)
        
        # 3. Похожие сигналы
        similar = self.find_similar_signals(symbol, pump_pct, combined_score, 5)
        similar_wins = len([s for s in similar if s['final_result'] and s['final_result'].startswith('WIN')])
        similar_wr = similar_wins / len(similar) if similar else 0.5
        
        # 4. Серия
        streak = self.get_streak_info(symbol)
        
        # 5. Оптимальные условия
        optimal = self.get_optimal_conditions(symbol)
        
        # === SCORING ===
        score = 5.0  # Базовый нейтральный
        
        # Историческая WR (+/- 2)
        if base_wr >= 0.7:
            score += 2.0
            reasoning.append(f"✅ Отличная историческая WR: {base_wr*100:.0f}%")
        elif base_wr >= 0.5:
            score += 0.5
        elif base_wr < 0.3 and total_signals >= 5:
            score -= 2.0
            reasoning.append(f"❌ Плохая историческая WR: {base_wr*100:.0f}%")
        
        # Weighted WR (если отличается от базовой - тренд!)
        if weighted_wr > base_wr + 0.1:
            score += 0.5
            reasoning.append(f"📈 Недавние сигналы лучше: {weighted_wr*100:.0f}%")
        elif weighted_wr < base_wr - 0.1:
            score -= 0.5
            reasoning.append(f"📉 Недавние сигналы хуже: {weighted_wr*100:.0f}%")
        
        # Похожие сигналы
        if similar and similar_wr >= 0.7:
            score += 1.0
            reasoning.append(f"🎯 Похожие сигналы работали: {similar_wr*100:.0f}% WR")
        elif similar and similar_wr < 0.3:
            score -= 1.0
            reasoning.append(f"⚠️ Похожие сигналы НЕ работали: {similar_wr*100:.0f}% WR")
        
        # Серия
        if streak['is_hot']:
            score += 0.5
            reasoning.append(f"🔥 HOT STREAK: {streak['current_streak']} побед подряд")
        elif streak['is_cold']:
            score -= 0.5
            reasoning.append(f"❄️ COLD STREAK: {abs(streak['current_streak'])} поражений подряд")
        
        # Оптимальные условия
        if optimal.get('has_data'):
            opt_range = optimal.get('optimal_pump_range', (10, 50))
            if opt_range[0] <= pump_pct <= opt_range[1]:
                score += 0.5
                reasoning.append(f"✅ Памп в оптимальном диапазоне: {opt_range[0]}-{opt_range[1]}%")
            
            best_hours = optimal.get('best_time_hours', [])
            if hour in best_hours:
                score += 0.5
                reasoning.append(f"⏰ Оптимальное время: {hour}:00 UTC")
        
        # Combined score бонус
        if combined_score >= 8:
            score += 1.0
        elif combined_score >= 7:
            score += 0.5
        elif combined_score < 5:
            score -= 1.0
        
        # Финальный score (0-10)
        final_score = max(0, min(10, score))
        
        # Prediction
        if final_score >= 8:
            prediction = 'STRONG_BUY'
        elif final_score >= 6:
            prediction = 'BUY'
        elif final_score >= 4:
            prediction = 'NEUTRAL'
        else:
            prediction = 'AVOID'
        
        # Confidence (на основе количества данных)
        if total_signals >= 20:
            confidence = 90
        elif total_signals >= 10:
            confidence = 70
        elif total_signals >= 5:
            confidence = 50
        else:
            confidence = 30
        
        return {
            'final_score': round(final_score, 1),
            'prediction': prediction,
            'confidence': confidence,
            'reasoning': reasoning,
            'factors': {
                'base_wr': round(base_wr, 2),
                'weighted_wr': round(weighted_wr, 2),
                'similar_wr': round(similar_wr, 2) if similar else None,
                'streak': streak['current_streak'],
                'total_signals': total_signals
            }
        }


# Глобальный экземпляр
_god_brain = None

def get_god_brain() -> GodBrain:
    global _god_brain
    if _god_brain is None:
        _god_brain = GodBrain()
    return _god_brain
