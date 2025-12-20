"""
Database - управление базой данных для хранения истории и обучения
"""

import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import json
from logger import get_logger

logger = get_logger()


class Database:
    """Класс для работы с SQLite базой данных"""
    
    def __init__(self, db_path: str = "data/pump_detector.db"):
        """
        Инициализация подключения к БД
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
        self._create_tables()
        logger.info(f"База данных инициализирована: {db_path}")
    
    def _get_connection(self) -> sqlite3.Connection:
        """Создать подключение к БД"""
        conn = sqlite3.Connection(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _create_tables(self):
        """Создать таблицы в БД если их нет"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Таблица обнаруженных пампов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pumps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                detected_at TIMESTAMP NOT NULL,
                price_start REAL NOT NULL,
                price_peak REAL NOT NULL,
                price_increase_pct REAL NOT NULL,
                volume_spike REAL NOT NULL,
                timeframe_minutes INTEGER NOT NULL,
                metadata TEXT
            )
        ''')
        
        # Таблица сгенерированных сигналов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pump_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                generated_at TIMESTAMP NOT NULL,
                entry_price REAL NOT NULL,
                stop_loss REAL,
                take_profit_1 REAL,
                take_profit_2 REAL,
                take_profit_3 REAL,
                risk_reward_ratio REAL,
                quality_score REAL NOT NULL,
                
                -- Факторы анализа
                divergence_score REAL,
                volume_drop_pct REAL,
                orderbook_score REAL,
                rsi_value REAL,
                
                -- Веса, использованные для этого сигнала
                weights TEXT NOT NULL,
                
                -- Исходы (заполняются позже)
                price_5m REAL,
                price_15m REAL,
                price_1h REAL,
                price_4h REAL,
                
                -- Эффективность
                was_profitable BOOLEAN,
                max_profitable_pct REAL,
                
                FOREIGN KEY (pump_id) REFERENCES pumps (id)
            )
        ''')
        
        # Таблица профилей монет
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS coin_profiles (
                symbol TEXT PRIMARY KEY,
                total_pumps INTEGER DEFAULT 0,
                total_signals INTEGER DEFAULT 0,
                successful_signals INTEGER DEFAULT 0,
                avg_pump_size_pct REAL,
                avg_dump_time_minutes REAL,
                avg_volatility REAL,
                reliability_score REAL DEFAULT 5.0,
                
                -- Адаптивные веса для этой монеты
                weight_divergence REAL DEFAULT 0.40,
                weight_volume REAL DEFAULT 0.30,
                weight_orderbook REAL DEFAULT 0.20,
                weight_rsi REAL DEFAULT 0.10,
                
                last_updated TIMESTAMP NOT NULL
            )
        ''')
        
        # Таблица настроек пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                chat_id TEXT PRIMARY KEY,
                enabled BOOLEAN DEFAULT TRUE,
                min_quality_score REAL DEFAULT 6.0,
                notifications_enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL
            )
        ''')
        
        # Индексы для ускорения запросов
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pumps_symbol ON pumps(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pumps_detected_at ON pumps(detected_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_generated_at ON signals(generated_at)')
        
        conn.commit()
        conn.close()
    
    def add_pump(self, symbol: str, price_start: float, price_peak: float,
                 price_increase_pct: float, volume_spike: float,
                 timeframe_minutes: int, metadata: Optional[Dict] = None) -> int:
        """
        Добавить обнаруженный памп в БД
        
        Returns:
            ID добавленного пампа
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO pumps (symbol, detected_at, price_start, price_peak,
                             price_increase_pct, volume_spike, timeframe_minutes, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            symbol,
            datetime.now(),
            price_start,
            price_peak,
            price_increase_pct,
            volume_spike,
            timeframe_minutes,
            json.dumps(metadata) if metadata else None
        ))
        
        pump_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Памп добавлен в БД: {symbol} +{price_increase_pct:.1f}% (ID: {pump_id})")
        return pump_id
    
    def add_signal(self, pump_id: int, symbol: str, entry_price: float,
                   stop_loss: float, take_profits: List[float],
                   risk_reward: float, quality_score: float,
                   factors: Dict, weights: Dict) -> int:
        """
        Добавить сгенерированный сигнал
        
        Returns:
            ID добавленного сигнала
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO signals (
                pump_id, symbol, generated_at, entry_price, stop_loss,
                take_profit_1, take_profit_2, take_profit_3,
                risk_reward_ratio, quality_score,
                divergence_score, volume_drop_pct, orderbook_score, rsi_value,
                weights
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            pump_id, symbol, datetime.now(), entry_price, stop_loss,
            take_profits[0] if len(take_profits) > 0 else None,
            take_profits[1] if len(take_profits) > 1 else None,
            take_profits[2] if len(take_profits) > 2 else None,
            risk_reward, quality_score,
            factors.get('divergence_score'),
            factors.get('volume_drop_pct'),
            factors.get('orderbook_score'),
            factors.get('rsi_value'),
            json.dumps(weights)
        ))
        
        signal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Сигнал добавлен: {symbol} @ {entry_price} (Качество: {quality_score:.1f}/10)")
        return signal_id
    
    def update_signal_outcome(self, signal_id: int, price_5m: Optional[float] = None,
                            price_15m: Optional[float] = None, price_1h: Optional[float] = None,
                            price_4h: Optional[float] = None):
        """Обновить исход сигнала (цены через время)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Получаем текущий сигнал
        cursor.execute('SELECT entry_price, stop_loss, take_profit_1 FROM signals WHERE id = ?', 
                      (signal_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return
        
        entry_price = row['entry_price']
        stop_loss = row['stop_loss']
        tp1 = row['take_profit_1']
        
        # Определяем прибыльность
        prices = [p for p in [price_5m, price_15m, price_1h, price_4h] if p is not None]
        if prices:
            # Для шорта: прибыльно если цена упала
            price_changes_pct = [(entry_price - p) / entry_price * 100 for p in prices]
            max_profit_pct = max(price_changes_pct)
            was_profitable = max_profit_pct > 0  # Цена должна упасть
        else:
            max_profit_pct = None
            was_profitable = None
        
        cursor.execute('''
            UPDATE signals
            SET price_5m = ?, price_15m = ?, price_1h = ?, price_4h = ?,
                was_profitable = ?, max_profitable_pct = ?
            WHERE id = ?
        ''', (price_5m, price_15m, price_1h, price_4h, was_profitable, max_profit_pct, signal_id))
        
        conn.commit()
        conn.close()
    
    def get_coin_profile(self, symbol: str) -> Optional[Dict]:
        """Получить профиль монеты"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM coin_profiles WHERE symbol = ?', (symbol,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def update_coin_profile(self, symbol: str, profile_data: Dict):
        """Обновить профиль монеты"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Проверяем существует ли профиль
        existing = self.get_coin_profile(symbol)
        
        if existing:
            # Обновляем существующий
            set_clause = ", ".join([f"{k} = ?" for k in profile_data.keys()])
            values = list(profile_data.values()) + [datetime.now(), symbol]
            cursor.execute(f'''
                UPDATE coin_profiles
                SET {set_clause}, last_updated = ?
                WHERE symbol = ?
            ''', values)
        else:
            # Создаём новый
            profile_data['symbol'] = symbol
            profile_data['last_updated'] = datetime.now()
            
            columns = ", ".join(profile_data.keys())
            placeholders = ", ".join(["?" for _ in profile_data])
            cursor.execute(f'''
                INSERT INTO coin_profiles ({columns})
                VALUES ({placeholders})
            ''', list(profile_data.values()))
        
        conn.commit()
        conn.close()
    
    def get_recent_signals(self, symbol: str, limit: int = 50) -> List[Dict]:
        """Получить недавние сигналы для монеты"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM signals
            WHERE symbol = ?
            ORDER BY generated_at DESC
            LIMIT ?
        ''', (symbol, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_statistics(self, symbol: Optional[str] = None) -> Dict:
        """Получить статистику по сигналам"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        where_clause = "WHERE symbol = ?" if symbol else ""
        params = (symbol,) if symbol else ()
        
        cursor.execute(f'''
            SELECT
                COUNT(*) as total_signals,
                SUM(CASE WHEN was_profitable = 1 THEN 1 ELSE 0 END) as profitable_signals,
                AVG(quality_score) as avg_quality,
                AVG(max_profitable_pct) as avg_profit_pct
            FROM signals
            {where_clause}
        ''', params)
        
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else {}
    
    def cleanup_old_data(self, days: int):
        """Удалить старые данные"""
        if days <= 0:
            return
        
        cutoff_date = datetime.now() - timedelta(days=days)
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM pumps WHERE detected_at < ?', (cutoff_date,))
        cursor.execute('DELETE FROM signals WHERE generated_at < ?', (cutoff_date,))
        
        deleted_pumps = cursor.rowcount
        conn.commit()
        conn.close()
        
        logger.info(f"Удалено {deleted_pumps} старых записей (старше {days} дней)")
