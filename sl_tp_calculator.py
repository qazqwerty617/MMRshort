"""
Ultra-Smart SL/TP Calculator v3
Оптимизированный под КАЖДУЮ монету и ситуацию.

Факторы:
1. ИСТОРИЯ МОНЕТЫ - как она обычно падает после пампов
2. СКОРОСТЬ пампа - быстрый = глубокий откат
3. ФОРМА СВЕЧИ - длинная верхняя тень = давление продавцов
4. ATR (волатильность) - для адаптивного стопа
5. ЛИКВИДНОСТЬ - стенки в стакане
6. ФИБОНАЧЧИ - классические уровни
"""

import math
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

try:
    from advanced_analyzers import AdvancedAnalyzer, PsychologyLevels
except ImportError:
    AdvancedAnalyzer = None
    PsychologyLevels = None

try:
    from god_eye import GodEye
except ImportError:
    GodEye = None

try:
    from dominator import Dominator
except ImportError:
    Dominator = None

try:
    from turbo_engine import TurboEngine, get_turbo_engine
except ImportError:
    TurboEngine = None
    get_turbo_engine = None

logger = logging.getLogger(__name__)


class UltraSmartCalculator:
    """
    Калькулятор SL/TP нового поколения.
    Адаптируется под каждую монету на основе её истории.
    """
    
    def __init__(self, database=None):
        """
        database: Экземпляр Database для запросов исторических данных
        """
        self.db = database
        self.coin_cache = {}  # Кеш исторических данных по монетам
        
        # Продвинутые анализаторы
        if AdvancedAnalyzer:
            self.advanced = AdvancedAnalyzer()
        else:
            self.advanced = None
        
        # 🔮 Глаз Бога
        if GodEye:
            self.god_eye = GodEye()
        else:
            self.god_eye = None
        
        # 🚀 Доминатор
        if Dominator:
            self.dominator = Dominator()
        else:
            self.dominator = None
        
        # ⚡ TURBO ENGINE (parallel)
        self.turbo_engine = get_turbo_engine() if get_turbo_engine else None
    
    def calculate(self, 
                  symbol: str,
                  entry_price: float,
                  peak_price: float,
                  start_price: float,
                  pump_speed_minutes: float,
                  klines: List = None,
                  orderbook: Dict = None) -> Dict:
        """
        Главный метод расчёта умных уровней.
        
        Args:
            symbol: Пара (например, RUSSELL_USDT)
            entry_price: Цена входа в шорт
            peak_price: Максимальная цена пампа
            start_price: Цена до пампа
            pump_speed_minutes: За сколько минут вырос
            klines: Последние свечи для анализа формы
            orderbook: Стакан для поиска ликвидности
        """
        try:
            pump_pct = ((peak_price - start_price) / start_price) * 100
            
            # ===== 1. ИСТОРИЧЕСКАЯ СТАТИСТИКА МОНЕТЫ =====
            coin_stats = self._get_coin_history(symbol)
            avg_dump_pct = coin_stats.get('avg_dump_pct', pump_pct * 0.5)  # Среднее падение после пампов
            dump_reliability = coin_stats.get('reliability', 0.5)  # Насколько стабильно падает
            total_pumps = coin_stats.get('total_pumps', 0)
            
            # ===== 2. МНОЖИТЕЛЬ СКОРОСТИ ПАМПА =====
            # Быстрый памп = острый откат, медленный = может проторговаться
            if pump_speed_minutes <= 2:
                speed_mult = 1.4  # Молниеносный - откат будет резким
            elif pump_speed_minutes <= 5:
                speed_mult = 1.2  # Быстрый
            elif pump_speed_minutes <= 10:
                speed_mult = 1.0  # Нормальный
            else:
                speed_mult = 0.8  # Медленный - возможна проторговка
            
            # ===== 3. АНАЛИЗ ФОРМЫ СВЕЧИ (если есть данные) =====
            candle_mult = 1.0
            candle_info = ""
            if klines and len(klines) > 0:
                candle_mult, candle_info = self._analyze_candle_structure(klines[-1])
            
            # ===== 4. ATR (ВОЛАТИЛЬНОСТЬ) =====
            atr_pct = 5.0  # Дефолт 5%
            if klines and len(klines) >= 14:
                atr_pct = self._calculate_atr_percent(klines, entry_price)
            
            # ===== 5. УРОВНИ ФИБОНАЧЧИ =====
            fib_range = peak_price - start_price
            fib_236 = peak_price - (fib_range * 0.236)
            fib_382 = peak_price - (fib_range * 0.382)
            fib_500 = peak_price - (fib_range * 0.500)
            fib_618 = peak_price - (fib_range * 0.618)
            fib_786 = peak_price - (fib_range * 0.786)
            
            # ===== 5.5 ADVANCED: Delta Volume и Ликвидации =====
            cvd_mult = 1.0
            liq_targets = []
            
            if self.advanced and klines:
                # Delta Volume
                cvd_analysis = self.advanced.delta.calculate_from_klines(klines)
                cvd_mult = self.advanced.delta.get_tp_multiplier(cvd_analysis)
                
                if cvd_analysis.get('divergence'):
                    logger.info(f"📉 {symbol}: CVD дивергенция! Усиление TP ×{cvd_mult:.2f}")
                
                # Ликвидации
                liq_levels = self.advanced.liquidation.calculate_liquidation_levels(
                    entry_price, peak_price, is_long=True
                )
                liq_targets = self.advanced.liquidation.get_tp_targets_from_liquidations(
                    liq_levels, entry_price
                )
            
            # ===== 6. КОМБИНИРОВАННЫЙ РАСЧЁТ TP =====
            # Базовые цели от Фибо
            base_tp1 = fib_382
            base_tp2 = fib_500
            base_tp3 = fib_618
            
            # Если у монеты есть история - корректируем под неё
            if total_pumps >= 3 and dump_reliability > 0.6:
                # Монета предсказуемая - используем её средний откат
                historical_drop = start_price + (fib_range * (1 - avg_dump_pct / 100))
                
                # Смешиваем Фибо и историю (60% история, 40% Фибо)
                base_tp2 = historical_drop * 0.6 + fib_500 * 0.4
                base_tp3 = historical_drop * 0.95 * 0.6 + fib_618 * 0.4  # Чуть глубже среднего
            
            # ===== 6.5 GOD EYE ANALYSIS =====
            god_eye_mult = 1.0
            god_eye_analysis = None
            god_eye_quality = "СТАНДАРТ"
            
            if self.god_eye and klines:
                god_eye_analysis = self.god_eye.analyze(symbol, klines, entry_price)
                god_eye_mult = self.god_eye.get_tp_multiplier(god_eye_analysis)
                god_eye_quality = self.god_eye.get_entry_quality(god_eye_analysis)
                
                score = god_eye_analysis.get('score', 5)
                confidence = god_eye_analysis.get('confidence', 0.5)
                logger.warning(f"🔮 {symbol}: GOD EYE Score {score:.1f}/10 | {god_eye_quality} | Conf: {confidence:.0%}")
            
            # ===== 6.6 DOMINATOR ANALYSIS =====
            dominator_mult = 1.0
            dominator_analysis = None
            domination_signal = "NEUTRAL"
            
            if self.dominator and klines and orderbook:
                dominator_analysis = self.dominator.dominate(
                    symbol=symbol,
                    klines=klines,
                    orderbook=orderbook,
                    entry_price=entry_price
                )
                dominator_mult = dominator_analysis.get('total_multiplier', 1.0)
                domination_signal = dominator_analysis.get('signal', 'NEUTRAL')
                
                dom_score = dominator_analysis.get('domination_score', 5)
                logger.warning(f"🚀 {symbol}: DOMINATOR Score {dom_score:.1f}/10 | {domination_signal} | Mult ×{dominator_mult:.2f}")
            
            # Применяем ВСЕ множители (ULTIMATE COMBO)
            final_mult = speed_mult * candle_mult * cvd_mult * god_eye_mult * dominator_mult
            
            tp1 = entry_price - (entry_price - base_tp1) * final_mult
            tp2 = entry_price - (entry_price - base_tp2) * final_mult
            tp3 = entry_price - (entry_price - base_tp3) * final_mult
            
            # ===== 7. КОРРЕКТИРОВКА ПО ЛИКВИДНОСТИ =====
            if orderbook:
                tp1 = self._adjust_to_liquidity(tp1, orderbook.get('bids', []))
                tp2 = self._adjust_to_liquidity(tp2, orderbook.get('bids', []))
                tp3 = self._adjust_to_liquidity(tp3, orderbook.get('bids', []))
            
            # ===== 8. ПСИХОЛОГИЧЕСКИЕ УРОВНИ =====
            if PsychologyLevels:
                tp1 = PsychologyLevels.snap_price(tp1, within_pct=1.0)
                tp2 = PsychologyLevels.snap_price(tp2, within_pct=1.0)
                tp3 = PsychologyLevels.snap_price(tp3, within_pct=1.0)
            
            # ===== 9. РАСЧЁТ СТОП-ЛОССА =====
            # Минимум: за пик + 1%
            # Адаптивно: ATR * 1.5
            min_sl = peak_price * 1.01
            atr_sl = entry_price * (1 + atr_pct * 1.5 / 100)
            sl = max(min_sl, atr_sl)
            
            # Ограничение: максимум 10% от входа
            max_sl = entry_price * 1.10
            sl = min(sl, max_sl)
            
            # ===== 10. ФОРМИРУЕМ РЕЗУЛЬТАТ =====
            result = {
                "stop_loss": sl,
                "take_profits": [tp1, tp2, tp3],
                "analysis": {
                    "pump_pct": pump_pct,
                    "speed_minutes": pump_speed_minutes,
                    "speed_mult": speed_mult,
                    "candle_mult": candle_mult,
                    "candle_info": candle_info,
                    "atr_pct": atr_pct,
                    "coin_history": {
                        "total_pumps": total_pumps,
                        "avg_dump_pct": avg_dump_pct,
                        "reliability": dump_reliability
                    },
                    "fib_levels": {
                        "38.2%": fib_382,
                        "50.0%": fib_500,
                        "61.8%": fib_618
                    },
                    "god_eye_score": god_eye_analysis.get('score', 5.0) if god_eye_analysis else 5.0,
                    "god_eye_quality": god_eye_quality,
                    "god_eye_confidence": god_eye_analysis.get('confidence', 0.5) if god_eye_analysis else 0.5,
                    "dominator_score": dominator_analysis.get('domination_score', 5.0) if dominator_analysis else 5.0,
                    "domination_signal": domination_signal,
                    "dominator_mult": dominator_mult,
                    "final_multiplier": final_mult
                }
            }
            
            logger.info(f"🧠 {symbol}: Smart TP рассчитан | Speed×{speed_mult:.1f} Candle×{candle_mult:.1f} | "
                       f"TP1={tp1:.8f} TP2={tp2:.8f} TP3={tp3:.8f}")
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка Ultra Smart Calculator: {e}")
            return self._fallback(entry_price)
    
    def _get_coin_history(self, symbol: str) -> Dict:
        """Получить историческую статистику падений монеты после пампов"""
        # Если есть база данных - запрашиваем
        if self.db:
            try:
                profile = self.db.get_coin_profile(symbol)
                if profile:
                    # Рассчитываем среднее падение из успешных сигналов
                    signals = self.db.get_signals_for_coin(symbol, limit=20)
                    if signals:
                        dumps = []
                        for s in signals:
                            if s.get('result_pct') and s['result_pct'] < 0:
                                dumps.append(abs(s['result_pct']))
                        if dumps:
                            return {
                                'avg_dump_pct': sum(dumps) / len(dumps),
                                'reliability': len(dumps) / len(signals),
                                'total_pumps': profile.get('total_pumps', 0)
                            }
            except Exception as e:
                logger.debug(f"Нет истории для {symbol}: {e}")
        
        # Дефолт - нет данных
        return {
            'avg_dump_pct': 25.0,  # Предполагаем средний откат 25%
            'reliability': 0.5,
            'total_pumps': 0
        }
    
    def _analyze_candle_structure(self, candle: List) -> Tuple[float, str]:
        """
        Анализ формы последней свечи.
        candle = [timestamp, open, high, low, close, volume]
        
        Returns:
            (multiplier, description)
        """
        try:
            _, open_p, high, low, close, _ = candle
            open_p, high, low, close = float(open_p), float(high), float(low), float(close)
            
            body = abs(close - open_p)
            upper_wick = high - max(open_p, close)
            lower_wick = min(open_p, close) - low
            total_range = high - low
            
            if total_range == 0:
                return 1.0, "Нет движения"
            
            upper_ratio = upper_wick / total_range
            body_ratio = body / total_range
            
            # Длинная верхняя тень = сильное давление продавцов
            if upper_ratio > 0.6:
                return 1.3, "💫 Длинная верхняя тень (сильные продажи)"
            
            # Падающая звезда / Инвертированный молот
            if upper_ratio > 0.4 and body_ratio < 0.3:
                return 1.2, "⭐ Падающая звезда"
            
            # Доджи - неопределенность
            if body_ratio < 0.1:
                return 0.9, "➖ Доджи (неопределенность)"
            
            # Большое красное тело
            if close < open_p and body_ratio > 0.7:
                return 1.15, "🔴 Сильная медвежья свеча"
            
            return 1.0, "Стандартная свеча"
            
        except Exception as e:
            logger.debug(f"Ошибка анализа свечи: {e}")
            return 1.0, ""
    
    def _calculate_atr_percent(self, klines: List, current_price: float) -> float:
        """Рассчитать ATR как процент от текущей цены"""
        try:
            trs = []
            for i in range(1, min(15, len(klines))):
                _, _, high, low, close_prev, _ = klines[i-1]
                _, _, high_cur, low_cur, _, _ = klines[i]
                
                high, low = float(high_cur), float(low_cur)
                close_prev = float(close_prev)
                
                tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
                trs.append(tr)
            
            if trs:
                atr = sum(trs) / len(trs)
                return (atr / current_price) * 100
        except Exception as e:
            logger.debug(f"Ошибка ATR: {e}")
        
        return 5.0  # Дефолт 5%
    
    def _adjust_to_liquidity(self, target: float, bids: List) -> float:
        """Притягиваем цель к ближайшей стенке в стакане (чуть выше неё)"""
        if not bids:
            return target
        
        best_wall = None
        best_vol = 0
        
        search_range = target * 0.03  # ±3%
        
        for item in bids:
            try:
                price = float(item[0])
                vol = float(item[1])
                
                if abs(price - target) <= search_range and vol > best_vol:
                    best_vol = vol
                    best_wall = price
            except:
                continue
        
        if best_wall and best_vol > 0:
            # Ставим TP чуть ВЫШЕ стенки (на 0.3%)
            return best_wall * 1.003
        
        return target
    
    def _snap_to_psychology(self, price: float) -> float:
        """
        Притягиваем к психологическим уровням (круглые числа).
        Например: 0.0100, 0.0050, 1.0000
        """
        # Определяем порядок величины
        if price <= 0:
            return price
            
        # Находим ближайшее "красивое" число в пределах 1%
        magnitude = 10 ** (len(str(int(1/price))) - 1) if price < 1 else 10 ** len(str(int(price)))
        
        # Упрощённо: округляем до 2-3 значащих цифр
        # Это можно улучшить для точного поиска круглых чисел
        return price  # Пока возвращаем как есть (TODO: улучшить)
    
    def _fallback(self, entry_price: float) -> Dict:
        """Резервные значения при ошибках"""
        return {
            "stop_loss": entry_price * 1.05,
            "take_profits": [
                entry_price * 0.92,
                entry_price * 0.85,
                entry_price * 0.75
            ],
            "analysis": {"fallback": True}
        }


# Для обратной совместимости
SmartCalculator = UltraSmartCalculator
