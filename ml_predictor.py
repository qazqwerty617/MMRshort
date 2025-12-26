"""
🤖 ML PREDICTOR v1.0 - Machine Learning для предсказания сигналов

Использует XGBoost-подобный алгоритм (Gradient Boosting) для предсказания
успеха сигнала на основе исторических данных.

ФИЛОСОФИЯ:
- Собираем данные из GOD BRAIN
- Обучаем модель на реальных WIN/LOSS
- Предсказываем вероятность успеха нового сигнала
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging
import math
import pickle
import os

logger = logging.getLogger(__name__)

# Попробуем импортировать sklearn, если есть
try:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    HAS_SKLEARN = True
    logger.info("🤖 ML Predictor: sklearn доступен, используем GradientBoosting")
except ImportError:
    HAS_SKLEARN = False
    logger.warning("🤖 ML Predictor: sklearn НЕ установлен, используем встроенный алгоритм")


class MLPredictor:
    """
    🤖 MACHINE LEARNING PREDICTOR
    
    Предсказывает успех сигнала на основе:
    - Исторических данных из GOD BRAIN
    - Feature engineering (pump_pct, scores, hour, etc.)
    - Gradient Boosting или встроенный алгоритм
    """
    
    def __init__(self, model_path: str = "data/ml_model.pkl"):
        self.model_path = model_path
        self.model = None
        self.scaler = None
        self.feature_names = [
            'pump_pct', 'combined_score', 'god_eye_score', 'dominator_score',
            'orderbook_score', 'oi_score', 'funding_score', 'btc_score', 
            'liq_score', 'pump_speed_minutes', 'hour'
        ]
        self.is_trained = False
        self.training_samples = 0
        
        # Для встроенного алгоритма (если нет sklearn)
        self.feature_weights = {}
        self.feature_thresholds = {}
        
        self._load_model()
    
    def _load_model(self):
        """Загрузить обученную модель если есть."""
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, 'rb') as f:
                    data = pickle.load(f)
                    self.model = data.get('model')
                    self.scaler = data.get('scaler')
                    self.is_trained = data.get('is_trained', False)
                    self.training_samples = data.get('training_samples', 0)
                    self.feature_weights = data.get('feature_weights', {})
                    self.feature_thresholds = data.get('feature_thresholds', {})
                logger.info(f"🤖 ML Model загружена ({self.training_samples} samples)")
            except Exception as e:
                logger.warning(f"Ошибка загрузки ML модели: {e}")
    
    def _save_model(self):
        """Сохранить обученную модель."""
        try:
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            with open(self.model_path, 'wb') as f:
                pickle.dump({
                    'model': self.model,
                    'scaler': self.scaler,
                    'is_trained': self.is_trained,
                    'training_samples': self.training_samples,
                    'feature_weights': self.feature_weights,
                    'feature_thresholds': self.feature_thresholds
                }, f)
            logger.info(f"🤖 ML Model сохранена")
        except Exception as e:
            logger.error(f"Ошибка сохранения ML модели: {e}")
    
    def train(self, db_path: str = "data/god_brain.db", min_samples: int = 20):
        """
        Обучить модель на исторических данных из GOD BRAIN.
        
        Args:
            db_path: Путь к базе GOD BRAIN
            min_samples: Минимум сэмплов для обучения
        
        Returns:
            bool: Успешно ли обучение
        """
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT pump_pct, combined_score, god_eye_score, dominator_score,
                   orderbook_score, oi_score, funding_score, btc_score, 
                   liq_score, pump_speed_minutes, created_at, final_result
            FROM signal_memory
            WHERE final_result IS NOT NULL
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        if len(rows) < min_samples:
            logger.info(f"🤖 ML: Недостаточно данных ({len(rows)}/{min_samples})")
            return False
        
        # Подготовка данных
        X = []
        y = []
        
        for row in rows:
            (pump_pct, combined, god_eye, dominator, ob, oi, funding, btc, 
             liq, speed, created, result) = row
            
            # Извлекаем час
            try:
                hour = datetime.fromisoformat(created).hour if created else 12
            except:
                hour = 12
            
            features = [
                pump_pct or 0,
                combined or 5,
                god_eye or 5,
                dominator or 5,
                ob or 5,
                oi or 5,
                funding or 5,
                btc or 5,
                liq or 5,
                speed or 5,
                hour
            ]
            
            X.append(features)
            y.append(1 if result and result.startswith('WIN') else 0)
        
        self.training_samples = len(X)
        
        if HAS_SKLEARN:
            return self._train_sklearn(X, y)
        else:
            return self._train_builtin(X, y)
    
    def _train_sklearn(self, X: List, y: List) -> bool:
        """Обучение с sklearn GradientBoosting."""
        try:
            import numpy as np
            
            X_arr = np.array(X)
            y_arr = np.array(y)
            
            # Нормализация
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X_arr)
            
            # Обучение
            self.model = GradientBoostingClassifier(
                n_estimators=50,
                max_depth=3,
                learning_rate=0.1,
                random_state=42
            )
            self.model.fit(X_scaled, y_arr)
            self.is_trained = True
            
            # Feature importance
            importances = self.model.feature_importances_
            for i, name in enumerate(self.feature_names):
                self.feature_weights[name] = round(importances[i], 4)
            
            # Сортируем по важности
            sorted_features = sorted(self.feature_weights.items(), 
                                    key=lambda x: x[1], reverse=True)
            
            logger.info(f"🤖 ML Model обучена на {self.training_samples} samples")
            logger.info(f"🤖 Top features: {sorted_features[:3]}")
            
            self._save_model()
            return True
            
        except Exception as e:
            logger.error(f"Ошибка обучения sklearn: {e}")
            return False
    
    def _train_builtin(self, X: List, y: List) -> bool:
        """Встроенный алгоритм обучения (без sklearn)."""
        try:
            # Простой feature importance на основе корреляции с результатом
            n = len(X)
            
            for i, name in enumerate(self.feature_names):
                feature_values = [x[i] for x in X]
                
                # Средние для WIN и LOSS
                win_vals = [v for v, label in zip(feature_values, y) if label == 1]
                loss_vals = [v for v, label in zip(feature_values, y) if label == 0]
                
                win_avg = sum(win_vals) / len(win_vals) if win_vals else 5
                loss_avg = sum(loss_vals) / len(loss_vals) if loss_vals else 5
                
                # Важность = разница средних
                importance = win_avg - loss_avg
                self.feature_weights[name] = round(importance, 4)
                
                # Порог = среднее для WIN
                self.feature_thresholds[name] = {
                    'win_avg': round(win_avg, 2),
                    'loss_avg': round(loss_avg, 2),
                    'threshold': round((win_avg + loss_avg) / 2, 2)
                }
            
            self.is_trained = True
            
            # Сортируем по важности
            sorted_features = sorted(self.feature_weights.items(), 
                                    key=lambda x: abs(x[1]), reverse=True)
            
            logger.info(f"🤖 ML Model (builtin) обучена на {self.training_samples} samples")
            logger.info(f"🤖 Top features: {sorted_features[:3]}")
            
            self._save_model()
            return True
            
        except Exception as e:
            logger.error(f"Ошибка встроенного обучения: {e}")
            return False
    
    def predict(self, signal_data: Dict) -> Dict:
        """
        Предсказать вероятность успеха сигнала.
        
        Args:
            signal_data: {
                'pump_pct': float,
                'combined_score': float,
                'god_eye_score': float,
                ...
                'hour': int (optional)
            }
        
        Returns:
            {
                'probability': float (0-1),
                'prediction': str ('WIN' / 'LOSS'),
                'confidence': str ('HIGH' / 'MEDIUM' / 'LOW' / 'NO_MODEL'),
                'feature_contributions': dict,
                'recommendation': str
            }
        """
        if not self.is_trained:
            return {
                'probability': 0.5,
                'prediction': 'UNKNOWN',
                'confidence': 'NO_MODEL',
                'feature_contributions': {},
                'recommendation': 'Модель не обучена (нужно больше данных)'
            }
        
        # Подготовка features
        hour = signal_data.get('hour', datetime.now().hour)
        features = [
            signal_data.get('pump_pct', 20),
            signal_data.get('combined_score', 5),
            signal_data.get('god_eye_score', 5),
            signal_data.get('dominator_score', 5),
            signal_data.get('orderbook_score', 5),
            signal_data.get('oi_score', 5),
            signal_data.get('funding_score', 5),
            signal_data.get('btc_score', 5),
            signal_data.get('liq_score', 5),
            signal_data.get('pump_speed_minutes', 5),
            hour
        ]
        
        if HAS_SKLEARN and self.model and self.scaler:
            return self._predict_sklearn(features)
        else:
            return self._predict_builtin(features)
    
    def _predict_sklearn(self, features: List) -> Dict:
        """Предсказание с sklearn."""
        try:
            import numpy as np
            
            X = np.array([features])
            X_scaled = self.scaler.transform(X)
            
            prob = self.model.predict_proba(X_scaled)[0][1]  # P(WIN)
            prediction = 'WIN' if prob >= 0.5 else 'LOSS'
            
            # Confidence
            if self.training_samples >= 50:
                confidence = 'HIGH'
            elif self.training_samples >= 20:
                confidence = 'MEDIUM'
            else:
                confidence = 'LOW'
            
            # Recommendation
            if prob >= 0.7:
                rec = '🟢 STRONG BUY - высокая вероятность успеха'
            elif prob >= 0.55:
                rec = '🟡 BUY - нормальная вероятность'
            elif prob >= 0.45:
                rec = '⚪ NEUTRAL - 50/50'
            elif prob >= 0.3:
                rec = '🟠 CAUTION - низкая вероятность'
            else:
                rec = '🔴 AVOID - очень низкая вероятность'
            
            return {
                'probability': round(prob, 3),
                'prediction': prediction,
                'confidence': confidence,
                'feature_contributions': self.feature_weights,
                'recommendation': rec,
                'training_samples': self.training_samples
            }
            
        except Exception as e:
            logger.error(f"Ошибка sklearn предсказания: {e}")
            return self._predict_builtin(features)
    
    def _predict_builtin(self, features: List) -> Dict:
        """Встроенное предсказание без sklearn."""
        try:
            # Считаем score на основе feature weights
            score = 0
            contributions = {}
            
            for i, name in enumerate(self.feature_names):
                value = features[i]
                weight = self.feature_weights.get(name, 0)
                
                # Нормализуем contribution
                if name in self.feature_thresholds:
                    threshold = self.feature_thresholds[name]['threshold']
                    contrib = (value - threshold) * weight * 0.1
                else:
                    contrib = 0
                
                score += contrib
                contributions[name] = round(contrib, 3)
            
            # Преобразуем в вероятность (sigmoid-like)
            prob = 1 / (1 + math.exp(-score)) if abs(score) < 10 else (1 if score > 0 else 0)
            prediction = 'WIN' if prob >= 0.5 else 'LOSS'
            
            # Confidence
            if self.training_samples >= 50:
                confidence = 'HIGH'
            elif self.training_samples >= 20:
                confidence = 'MEDIUM'
            else:
                confidence = 'LOW'
            
            # Recommendation
            if prob >= 0.7:
                rec = '🟢 STRONG BUY'
            elif prob >= 0.55:
                rec = '🟡 BUY'
            elif prob >= 0.45:
                rec = '⚪ NEUTRAL'
            elif prob >= 0.3:
                rec = '🟠 CAUTION'
            else:
                rec = '🔴 AVOID'
            
            return {
                'probability': round(prob, 3),
                'prediction': prediction,
                'confidence': confidence,
                'feature_contributions': contributions,
                'recommendation': rec,
                'training_samples': self.training_samples
            }
            
        except Exception as e:
            logger.error(f"Ошибка builtin предсказания: {e}")
            return {
                'probability': 0.5,
                'prediction': 'UNKNOWN',
                'confidence': 'ERROR',
                'feature_contributions': {},
                'recommendation': 'Ошибка предсказания'
            }
    
    def get_status(self) -> Dict:
        """Получить статус ML модели."""
        return {
            'is_trained': self.is_trained,
            'training_samples': self.training_samples,
            'has_sklearn': HAS_SKLEARN,
            'top_features': sorted(self.feature_weights.items(), 
                                  key=lambda x: abs(x[1]), reverse=True)[:5] if self.feature_weights else []
        }


# Глобальный экземпляр
_ml_predictor = None

def get_ml_predictor() -> MLPredictor:
    global _ml_predictor
    if _ml_predictor is None:
        _ml_predictor = MLPredictor()
    return _ml_predictor
