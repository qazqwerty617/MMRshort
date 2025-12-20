"""
Coin Profiler - машинное обучение и профилирование монет
"""

from typing import Dict, List, Optional
from database import Database
import numpy as np
from logger import get_logger

logger = get_logger()


class CoinProfiler:
    """Класс для обучения и адаптации под каждую монету"""
    
    def __init__(self, database: Database, config: Dict):
        """
        Инициализация профайлера
        
        Args:
            database: Экземпляр базы данных
            config: Конфигурация из config.yaml секции 'learning'
        """
        self.db = database
        self.config = config
        self.enabled = config['enabled']
        self.min_signals = config['min_signals_for_learning']
        self.learning_rate = config['learning_rate']
        self.initial_weights = config['initial_weights']
    
    def get_weights_for_coin(self, symbol: str) -> Dict[str, float]:
        """
        Получить веса факторов для конкретной монеты
        
        Args:
            symbol: Символ монеты
            
        Returns:
            Словарь весов {"divergence": 0.4, "volume_drop": 0.3, ...}
        """
        if not self.enabled:
            return self.initial_weights
        
        # Получаем профиль из БД
        profile = self.db.get_coin_profile(symbol)
        
        if profile and profile['total_signals'] >= self.min_signals:
            # Используем адаптированные веса
            return {
                "divergence": profile['weight_divergence'],
                "volume_drop": profile['weight_volume'],
                "orderbook": profile['weight_orderbook'],
                "rsi_level": profile['weight_rsi']
            }
        else:
            # Используем начальные веса
            return self.initial_weights.copy()
    
    def update_coin_statistics(self, symbol: str, pump_data: Dict):
        """
        Обновить статистику пампа для монеты
        
        Args:
            symbol: Символ
            pump_data: Данные о пампе
        """
        profile = self.db.get_coin_profile(symbol)
        
        if profile:
            # Обновляем существующий профиль
            new_pumps = profile['total_pumps'] + 1
            
            # Обновляем средний размер пампа
            if profile['avg_pump_size_pct']:
                avg_pump = (profile['avg_pump_size_pct'] * profile['total_pumps'] + 
                           pump_data['increase_pct']) / new_pumps
            else:
                avg_pump = pump_data['increase_pct']
            
            self.db.update_coin_profile(symbol, {
                'total_pumps': new_pumps,
                'avg_pump_size_pct': avg_pump
            })
        else:
            # Создаём новый профиль
            self.db.update_coin_profile(symbol, {
                'total_pumps': 1,
                'avg_pump_size_pct': pump_data['increase_pct'],
                'total_signals': 0,
                'successful_signals': 0,
                **self.initial_weights  # Начальные веса
            })
        
        logger.debug(f"Обновлена статистика пампов для {symbol}")
    
    def learn_from_signal_outcome(self, signal_id: int):
        """
        Обучиться на основе исхода сигнала
        
        Args:
            signal_id: ID сигнала в БД
        """
        if not self.enabled:
            return
        
        # Получаем сигнал из БД
        signals = self.db.get_recent_signals("", limit=1000)
        signal = next((s for s in signals if s['id'] == signal_id), None)
        
        if not signal or signal['was_profitable'] is None:
            return
        
        symbol = signal['symbol']
        was_profitable = bool(signal['was_profitable'])
        
        # Получаем текущий профиль
        profile = self.db.get_coin_profile(symbol)
        if not profile:
            logger.warning(f"Профиль для {symbol} не найден")
            return
        
        # Обновляем статистику
        new_total = profile['total_signals'] + 1
        new_successful = profile['successful_signals'] + (1 if was_profitable else 0)
        
        # Рассчитываем успешность
        success_rate = new_successful / new_total if new_total > 0 else 0.5
        
        # Обновляем рейтинг надёжности (1-10)
        reliability = success_rate * 10.0
        
        # Адаптируем веса, если сигналов достаточно
        if new_total >= self.min_signals:
            weights = self._adapt_weights(signal, was_profitable, profile)
        else:
            weights = {
                'weight_divergence': profile['weight_divergence'],
                'weight_volume': profile['weight_volume'],
                'weight_orderbook': profile['weight_orderbook'],
                'weight_rsi': profile['weight_rsi']
            }
        
        # Сохраняем обновлённый профиль
        self.db.update_coin_profile(symbol, {
            'total_signals': new_total,
            'successful_signals': new_successful,
            'reliability_score': reliability,
            **weights
        })
        
        logger.info(f"Обучение на {symbol}: {new_successful}/{new_total} успешных "
                   f"(надёжность: {reliability:.1f}/10)")
    
    def _adapt_weights(self, signal: Dict, was_profitable: bool, 
                      profile: Dict) -> Dict[str, float]:
        """
        Адаптировать веса факторов на основе исхода
        
        Args:
            signal: Данные сигнала
            was_profitable: Был ли сигнал прибыльным
            profile: Текущий профиль монеты
            
        Returns:
            Обновлённые веса
        """
        # Текущие веса
        weights = {
            'divergence': profile['weight_divergence'],
            'volume': profile['weight_volume'],
            'orderbook': profile['weight_orderbook'],
            'rsi': profile['weight_rsi']
        }
        
        # Факторы сигнала (нормализованные 0-1)
        factors = {
            'divergence': (signal['divergence_score'] or 0) / 10.0,
            'volume': (signal['volume_drop_pct'] or 0) / 100.0,
            'orderbook': (signal['orderbook_score'] or 0) / 10.0,
            'rsi': max(0, signal['rsi_value'] - 50) / 50.0 if signal['rsi_value'] else 0
        }
        
        # Обновляем веса на основе исхода
        for factor_name, factor_value in factors.items():
            weight_key = f'weight_{factor_name}'
            current_weight = weights[factor_name]
            
            # Если сигнал был прибыльным и фактор был сильным - увеличиваем вес
            # Если сигнал был убыточным и фактор был сильным - уменьшаем вес
            if was_profitable:
                adjustment = self.learning_rate * factor_value
            else:
                adjustment = -self.learning_rate * factor_value
            
            # Обновляем вес с ограничениями (0.05 - 0.60)
            new_weight = max(0.05, min(0.60, current_weight + adjustment))
            weights[factor_name] = new_weight
        
        # Нормализуем веса чтобы сумма = 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        
        return {
            'weight_divergence': weights['divergence'],
            'weight_volume': weights['volume'],
            'weight_orderbook': weights['orderbook'],
            'weight_rsi': weights['rsi']
        }
    
    def get_coin_reliability(self, symbol: str) -> float:
        """
        Получить рейтинг надёжности монеты (1-10)
        
        Args:
            symbol: Символ монеты
            
        Returns:
            Рейтинг надёжности
        """
        profile = self.db.get_coin_profile(symbol)
        
        if profile and profile['total_signals'] >= self.min_signals:
            return profile['reliability_score']
        
        return 5.0  # Средняя надёжность по умолчанию
