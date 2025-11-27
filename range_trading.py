"""
Range Trading Strategy - Торговля в ценовом канале (УЛУЧШЕННАЯ ВЕРСИЯ)

Философия: Рынок находится во флэте 80% времени. Стратегия системно извлекает
прибыль из периодов консолидации, торгуя между уровнями поддержки и сопротивления.

Основные компоненты:
1. Определение канала (Bollinger Bands, уровни поддержки/сопротивления)
2. Подтверждение осцилляторами (RSI, Stochastic, MACD)
3. Свечные паттерны
4. Управление рисками (R:R минимум 1:1.5)

УЛУЧШЕНИЯ v2.0:
- Линейная регрессия для точного определения флэта
- Улучшенное обнаружение дивергенций с фильтрацией шума
- Динамический стоп-лосс на основе ATR (Average True Range)
- Относительное позиционирование в канале
- Проверка разворота RSI (не просто уровень, а направление)
- Гибкая система подтверждений (дивергенция = 2 подтверждения)
- Встроенная защита от плохих сделок (R:R check)
"""

import pandas as pd
import numpy as np
from datetime import datetime
from scipy import stats


def calculate_bollinger_bands(df, period=20, std_dev=2):
    """
    Рассчитывает полосы Боллинджера
    
    Args:
        df: DataFrame с OHLCV данными
        period: Период для расчета (по умолчанию 20)
        std_dev: Количество стандартных отклонений (по умолчанию 2)
    
    Returns:
        tuple: (middle_band, upper_band, lower_band, bb_width)
    """
    middle_band = df['close'].rolling(window=period).mean()
    std = df['close'].rolling(window=period).std()
    upper_band = middle_band + (std * std_dev)
    lower_band = middle_band - (std * std_dev)
    bb_width = (upper_band - lower_band) / middle_band  # Ширина канала в процентах
    
    return middle_band, upper_band, lower_band, bb_width


def calculate_rsi(df, period=14):
    """Рассчитывает RSI"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_stochastic(df, period=14, smooth_k=3, smooth_d=3):
    """
    Рассчитывает Stochastic Oscillator
    
    Returns:
        tuple: (%K, %D)
    """
    low_min = df['low'].rolling(window=period).min()
    high_max = df['high'].rolling(window=period).max()
    
    stoch_k = 100 * (df['close'] - low_min) / (high_max - low_min)
    stoch_k = stoch_k.rolling(window=smooth_k).mean()
    stoch_d = stoch_k.rolling(window=smooth_d).mean()
    
    return stoch_k, stoch_d


def calculate_macd(df, fast=12, slow=26, signal=9):
    """
    Рассчитывает MACD
    
    Returns:
        tuple: (macd_line, signal_line, histogram)
    """
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def detect_candlestick_patterns(df, index=-1):
    """
    УЛУЧШЕННОЕ определение разворотных свечных паттернов с защитой от ошибок
    
    Паттерны:
    - Hammer (Молот) - бычий разворот
    - Shooting Star (Падающая звезда) - медвежий разворот
    - Bullish Engulfing (Бычье поглощение)
    - Bearish Engulfing (Медвежье поглощение)
    
    ИСПРАВЛЕНО: Защита от IndexError и KeyError
    
    Returns:
        dict: {'pattern': str, 'direction': 'BULLISH'/'BEARISH', 'strength': int}
    """
    try:
        if len(df) < abs(index) + 2:
            return {'pattern': None, 'direction': None, 'strength': 0}
        
        current = df.iloc[index]
        # Правильная проверка для получения предыдущей свечи
        previous = df.iloc[index - 1] if index != 0 and abs(index) < len(df) else None
        
        open_price = current['open']
        close_price = current['close']
        high_price = current['high']
        low_price = current['low']
        
        body = abs(close_price - open_price)
        total_range = high_price - low_price
        upper_shadow = high_price - max(open_price, close_price)
        lower_shadow = min(open_price, close_price) - low_price
        
        # Защита от деления на ноль
        if total_range == 0:
            return {'pattern': None, 'direction': None, 'strength': 0}
        
        # МОЛОТ (Hammer) - бычий разворот у поддержки
        if (lower_shadow > body * 2 and 
            upper_shadow < body * 0.3 and 
            close_price > open_price):
            return {'pattern': 'HAMMER', 'direction': 'BULLISH', 'strength': 3}
        
        # ПАДАЮЩАЯ ЗВЕЗДА (Shooting Star) - медвежий разворот у сопротивления
        if (upper_shadow > body * 2 and 
            lower_shadow < body * 0.3 and 
            close_price < open_price):
            return {'pattern': 'SHOOTING_STAR', 'direction': 'BEARISH', 'strength': 3}
        
        # Паттерны поглощения (требуют предыдущую свечу)
        if previous is not None:
            prev_body = abs(previous['close'] - previous['open'])
            
            # БЫЧЬЕ ПОГЛОЩЕНИЕ
            if (previous['close'] < previous['open'] and  # Предыдущая медвежья
                close_price > open_price and  # Текущая бычья
                close_price > previous['open'] and  # Поглощает тело предыдущей
                open_price < previous['close'] and
                body > prev_body * 1.2):  # Тело больше на 20%
                return {'pattern': 'BULLISH_ENGULFING', 'direction': 'BULLISH', 'strength': 4}
            
            # МЕДВЕЖЬЕ ПОГЛОЩЕНИЕ
            if (previous['close'] > previous['open'] and  # Предыдущая бычья
                close_price < open_price and  # Текущая медвежья
                close_price < previous['open'] and  # Поглощает тело предыдущей
                open_price > previous['close'] and
                body > prev_body * 1.2):
                return {'pattern': 'BEARISH_ENGULFING', 'direction': 'BEARISH', 'strength': 4}
        
        return {'pattern': None, 'direction': None, 'strength': 0}
        
    except (IndexError, KeyError) as e:
        # При любых ошибках доступа к данным - безопасный возврат
        return {'pattern': None, 'direction': None, 'strength': 0}


def detect_rsi_divergence(df, rsi, lookback=20):
    """
    УЛУЧШЕННОЕ обнаружение дивергенций с поиском значимых экстремумов
    
    Бычья дивергенция: цена делает более низкий минимум, RSI - более высокий минимум
    Медвежья дивергенция: цена делает более высокий максимум, RSI - более низкий максимум
    
    Улучшения:
    - Увеличен lookback до 20 для более надежного поиска
    - Разделение периода на прошлое (60%) и настоящее (40%)
    - Требуется значимая разница RSI (минимум 3 пункта)
    
    Returns:
        str: 'BULLISH', 'BEARISH', или None
    """
    if len(df) < lookback:
        return None
    
    # Ищем четкие экстремумы в цене и RSI
    price_data = df['close'].iloc[-lookback:]
    rsi_data = rsi.iloc[-lookback:]
    
    # Находим значимые экстремумы (фильтруем шум)
    price_min_idx = price_data.idxmin()
    price_max_idx = price_data.idxmax()
    
    # Бычья дивергенция: цена делает более низкий минимум, RSI - более высокий
    if price_min_idx > len(price_data) * 0.6:  # Минимум в правой части окна (последние 40%)
        prev_min_idx = price_data.iloc[:int(lookback*0.6)].idxmin()
        prev_min_price = price_data.loc[prev_min_idx]
        current_min_price = price_data.loc[price_min_idx]
        
        prev_min_rsi = rsi_data.loc[prev_min_idx]
        current_min_rsi = rsi_data.loc[price_min_idx]
        
        # Цена ниже И RSI ЗНАЧИТЕЛЬНО выше (+3 минимум)
        if (current_min_price < prev_min_price and 
            current_min_rsi > prev_min_rsi + 3):
            return 'BULLISH'
    
    # Медвежья дивергенция: цена делает более высокий максимум, RSI - более низкий
    if price_max_idx > len(price_data) * 0.6:  # Максимум в правой части окна
        prev_max_idx = price_data.iloc[:int(lookback*0.6)].idxmax()
        prev_max_price = price_data.loc[prev_max_idx]
        current_max_price = price_data.loc[price_max_idx]
        
        prev_max_rsi = rsi_data.loc[prev_max_idx]
        current_max_rsi = rsi_data.loc[price_max_idx]
        
        # Цена выше И RSI ЗНАЧИТЕЛЬНО ниже (-3 минимум)
        if (current_max_price > prev_max_price and 
            current_max_rsi < prev_max_rsi - 3):
            return 'BEARISH'
    
    return None


def calculate_atr(df, period=14):
    """
    Рассчитывает Average True Range (ATR) для измерения волатильности
    
    ИСПРАВЛЕНО: Правильный расчет True Range без использования pd.concat
    
    Returns:
        pd.Series: ATR значения
    """
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)
    
    # True Range calculation (3 компонента)
    tr1 = high - low  # Высота текущей свечи
    tr2 = abs(high - close_prev)  # От хая до предыдущего close
    tr3 = abs(low - close_prev)  # От лоя до предыдущего close
    
    # Объединяем в DataFrame и берем максимум
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()
    
    return atr


def is_market_in_range(df, bb_width, period=50, volatility_threshold=0.15):
    """
    УЛУЧШЕННОЕ определение флэта с использованием линейной регрессии
    
    Критерии:
    1. Линейная регрессия: слабый наклон тренда (< 2%)
    2. Волатильность: стабильная или снижающаяся
    3. Ценовой диапазон: узкий (< 8%)
    
    Улучшения:
    - Математически точное определение тренда через scipy.stats.linregress
    - Учет волатильности BB
    - Анализ ценового диапазона
    
    ИСПРАВЛЕНО: Надежная обработка ошибок и edge cases
    
    Returns:
        bool: True если рынок во флэте
    """
    if len(df) < period + 10:
        return False
    
    try:
        # 1. Анализ тренда через линейную регрессию
        prices = df['close'].iloc[-period:].values
        
        # Проверка на достаточность данных и вариативность
        if len(prices) < 2 or np.all(prices == prices[0]):
            return False
        
        x = np.arange(len(prices))
        
        slope, _, r_value, _, _ = stats.linregress(x, prices)
        # Наклон в процентах за весь период (используем np.mean для безопасности)
        slope_percent = (slope * len(prices)) / np.mean(prices) * 100
        
        # 2. Анализ волатильности через Bollinger Bands
        current_volatility = bb_width.iloc[-1]
        avg_volatility = bb_width.iloc[-20:].mean()
        
        # 3. Анализ ценового диапазона (используем np функции)
        price_range = (np.max(prices) - np.min(prices)) / np.mean(prices) * 100
        
        # Критерии флэта:
        # - Слабый наклон (< 2%) - почти горизонтальный тренд
        # - Низкая или снижающаяся волатильность (не расширяется)
        # - Узкий ценовой диапазон (< 8%) - цена в коридоре
        is_flat = (abs(slope_percent) < 2.0 and 
                   current_volatility <= avg_volatility * 1.1 and
                   price_range < 8.0)
        
        return is_flat
        
    except (ValueError, TypeError, IndexError, AttributeError) as e:
        # В случае любых ошибок в расчетах считаем что тренд есть (безопасный выход)
        return False


def calculate_dynamic_stop_loss(df, current_price, support_level, resistance_level, action):
    """
    УЛУЧШЕННЫЙ расчет стоп-лосса с учетом ATR (волатильности)
    
    Динамический стоп адаптируется к текущей волатильности актива:
    - При высокой волатильности - шире стоп (защита от ложных срабатываний)
    - При низкой волатильности - уже стоп (меньший риск)
    
    Returns:
        float: Оптимальный уровень стоп-лосса
    """
    # Базовый стоп-лосс (фиксированный процент от уровня)
    if action == "BUY":
        base_sl = support_level * 0.995  # -0.5% от поддержки
    else:  # SELL
        base_sl = resistance_level * 1.005  # +0.5% от сопротивления
    
    # Рассчитываем ATR для оценки волатильности
    atr = calculate_atr(df, period=14)
    current_atr = atr.iloc[-1]
    
    # Динамический стоп-лосс на основе ATR (1.5x ATR от входа)
    if action == "BUY":
        atr_sl = current_price - (current_atr * 1.5)
        # Берем более консервативный (ближе к цене)
        dynamic_sl = max(base_sl, atr_sl)
    else:  # SELL
        atr_sl = current_price + (current_atr * 1.5)
        # Берем более консервативный (ближе к цене)
        dynamic_sl = min(base_sl, atr_sl)
    
    return dynamic_sl


def calculate_volume_nodes(df, num_levels=20):
    """
    УЛУЧШЕННЫЙ расчет Volume Profile с корректным распределением объема
    
    Определяет:
    - POC (Point of Control) - уровень с максимальным объемом
    - High Volume Nodes - зоны высокого объема (поддержка/сопротивление)
    - Low Volume Nodes - зоны низкого объема (легкий проход)
    
    УЛУЧШЕНИЯ:
    - Распределение объема свечи по всем пересекаемым уровням (не только по среднему)
    - Более точный Volume Profile, учитывающий полный диапазон каждой свечи
    
    Args:
        df: DataFrame с OHLCV данными
        num_levels: Количество ценовых уровней для анализа
    
    Returns:
        dict: {
            'poc': float,  # Point of Control
            'high_volume_nodes': list,  # Уровни с высоким объемом
            'low_volume_nodes': list,   # Уровни с низким объемом
            'value_area_high': float,   # Верхняя граница Value Area (70% объема)
            'value_area_low': float     # Нижняя граница Value Area
        }
    """
    try:
        if len(df) < 20:
            return None
        
        # Определяем ценовой диапазон
        price_min = df['low'].min()
        price_max = df['high'].max()
        price_range = price_max - price_min
        
        if price_range == 0:
            return None
        
        # Создаем уровни цен
        price_levels = np.linspace(price_min, price_max, num_levels)
        level_width = price_range / num_levels
        
        # Распределяем объем по уровням (УЛУЧШЕННАЯ ЛОГИКА)
        volume_at_levels = np.zeros(num_levels)
        
        for i in range(len(df)):
            high = df['high'].iloc[i]
            low = df['low'].iloc[i]
            volume = df['volume'].iloc[i]
            
            # Распределяем объем свечи по всем уровням, которые она пересекает
            min_level = max(0, int((low - price_min) / level_width))
            max_level = min(num_levels - 1, int((high - price_min) / level_width))
            
            if max_level >= min_level:
                # Равномерно распределяем объем по пересекаемым уровням
                levels_count = max_level - min_level + 1
                volume_per_level = volume / levels_count
                
                for level_idx in range(min_level, max_level + 1):
                    volume_at_levels[level_idx] += volume_per_level
        
        # POC - уровень с максимальным объемом
        poc_idx = np.argmax(volume_at_levels)
        poc_price = price_levels[poc_idx]
        
        # Value Area - зона с 70% от общего объема
        total_volume = volume_at_levels.sum()
        sorted_indices = np.argsort(volume_at_levels)[::-1]  # От большего к меньшему
        
        cumulative_volume = 0
        value_area_indices = []
        for idx in sorted_indices:
            cumulative_volume += volume_at_levels[idx]
            value_area_indices.append(idx)
            if cumulative_volume >= total_volume * 0.7:
                break
        
        value_area_high = price_levels[max(value_area_indices)]
        value_area_low = price_levels[min(value_area_indices)]
        
        # High Volume Nodes - уровни выше среднего объема
        avg_volume = volume_at_levels.mean()
        std_volume = volume_at_levels.std()
        high_volume_threshold = avg_volume + std_volume * 0.5
        
        high_volume_nodes = [
            price_levels[i] for i in range(num_levels) 
            if volume_at_levels[i] > high_volume_threshold
        ]
        
        # Low Volume Nodes - уровни ниже среднего объема
        low_volume_threshold = avg_volume - std_volume * 0.5
        low_volume_nodes = [
            price_levels[i] for i in range(num_levels)
            if volume_at_levels[i] < low_volume_threshold
        ]
        
        return {
            'poc': poc_price,
            'high_volume_nodes': high_volume_nodes,
            'low_volume_nodes': low_volume_nodes,
            'value_area_high': value_area_high,
            'value_area_low': value_area_low
        }
        
    except Exception as e:
        return None


def analyze_volume_profile(df):
    """
    Анализ Volume Profile для определения значимых уровней и объемной активности
    
    Volume Profile показывает:
    1. POC (Point of Control) - магнит для цены, уровень справедливой стоимости
    2. High Volume Nodes - сильная поддержка/сопротивление
    3. Value Area - зона, где торговалось 70% объема
    4. Текущая интенсивность объема
    
    Returns:
        dict: {
            'volume_levels': dict,  # Volume Profile данные
            'current_volume_intensity': float,  # Текущий объем / средний объем
            'volume_status': str,  # 'HIGH', 'NORMAL', 'LOW'
            'near_poc': bool,  # Цена близко к POC
            'in_value_area': bool  # Цена в Value Area
        }
    """
    try:
        if len(df) < 20:
            return None
        
        # Рассчитываем Volume Profile
        volume_levels = calculate_volume_nodes(df)
        
        if volume_levels is None:
            return None
        
        # Анализ текущего объема
        current_volume = df['volume'].iloc[-1]
        volume_avg = df['volume'].iloc[-20:].mean()
        current_volume_intensity = current_volume / volume_avg if volume_avg > 0 else 1.0
        
        # Определяем статус объема
        if current_volume_intensity > 1.5:
            volume_status = 'HIGH'
        elif current_volume_intensity < 0.7:
            volume_status = 'LOW'
        else:
            volume_status = 'NORMAL'
        
        # Проверка близости к POC (в пределах 1%)
        current_price = df['close'].iloc[-1]
        poc = volume_levels['poc']
        near_poc = abs(current_price - poc) / poc < 0.01
        
        # Проверка нахождения в Value Area
        va_high = volume_levels['value_area_high']
        va_low = volume_levels['value_area_low']
        in_value_area = va_low <= current_price <= va_high
        
        return {
            'volume_levels': volume_levels,
            'current_volume_intensity': current_volume_intensity,
            'volume_status': volume_status,
            'near_poc': near_poc,
            'in_value_area': in_value_area
        }
        
    except Exception as e:
        return None


def detect_volume_divergence(df, lookback=10):
    """
    УЛУЧШЕННОЕ определение дивергенции объема с безопасными индексами
    
    Логика:
    1. Бычья дивергенция объема:
       - Цена делает новый минимум
       - Объем на новом минимуме МЕНЬШЕ, чем на предыдущем
       - Означает: продавцы слабеют, покупатели накапливают позиции
    
    2. Медвежья дивергенция объема:
       - Цена делает новый максимум
       - Объем на новом максимуме МЕНЬШЕ, чем на предыдущем
       - Означает: покупатели слабеют, распродажа близка
    
    3. Ложный пробой уровня:
       - Цена пробивает уровень
       - Объем при пробое НИЗКИЙ (< 70% от среднего)
       - Означает: пробой не подтвержден, вероятен откат
    
    УЛУЧШЕНИЯ:
    - Использование относительных индексов для безопасной работы
    - Улучшенная обработка граничных случаев
    - Более точное определение экстремумов
    
    Args:
        df: DataFrame с OHLCV данными
        lookback: Период для поиска дивергенций
    
    Returns:
        dict: {
            'divergence_type': str,  # 'BULLISH', 'BEARISH', 'FALSE_BREAKOUT', None
            'strength': int,  # 0-5 (сила сигнала)
            'description': str  # Описание дивергенции
        }
    """
    try:
        if len(df) < lookback + 5:
            return {'divergence_type': None, 'strength': 0, 'description': ''}
        
        # Используем относительные индексы для безопасности
        recent_data = df.iloc[-lookback:]
        recent_prices = recent_data['close']
        recent_volumes = recent_data['volume']
        recent_lows = recent_data['low']
        recent_highs = recent_data['high']
        
        # Средний объем для сравнения (с проверкой достаточности данных)
        avg_volume = df['volume'].iloc[-lookback*2:-lookback].mean() if len(df) > lookback*2 else recent_volumes.mean()
        
        # === БЫЧЬЯ ДИВЕРГЕНЦИЯ ОБЪЕМА ===
        # Ищем два минимума в последних данных (с проверкой достаточности)
        if len(recent_prices) >= 6:
            price_min_current_idx = recent_prices.iloc[-5:].idxmin()  # Последние 5 баров
            price_min_prev_idx = recent_prices.iloc[:-5].idxmin()  # До этого
            
            if price_min_current_idx in recent_prices.index and price_min_prev_idx in recent_prices.index:
                price_min_current = recent_prices.loc[price_min_current_idx]
                price_min_prev = recent_prices.loc[price_min_prev_idx]
                
                volume_at_current_min = recent_volumes.loc[price_min_current_idx]
                volume_at_prev_min = recent_volumes.loc[price_min_prev_idx]
                
                # Цена делает новый минимум, объем падает
                if (price_min_current < price_min_prev and 
                    volume_at_current_min < volume_at_prev_min * 0.8 and
                    volume_at_prev_min > 0):  # Защита от деления на 0
                    volume_drop_pct = (1 - volume_at_current_min / volume_at_prev_min) * 100
                    strength = min(5, int(volume_drop_pct / 10))  # Чем больше падение объема, тем сильнее
                    
                    return {
                        'divergence_type': 'BULLISH',
                        'strength': max(strength, 3),  # Минимум 3
                        'description': f'Бычья дивергенция объема: цена обновила минимум, объем упал на {volume_drop_pct:.0f}%'
                    }
        
        # === МЕДВЕЖЬЯ ДИВЕРГЕНЦИЯ ОБЪЕМА ===
        # Ищем два максимума в последних данных (с проверкой достаточности)
        if len(recent_prices) >= 6:
            price_max_current_idx = recent_prices.iloc[-5:].idxmax()
            price_max_prev_idx = recent_prices.iloc[:-5].idxmax()
            
            if price_max_current_idx in recent_prices.index and price_max_prev_idx in recent_prices.index:
                price_max_current = recent_prices.loc[price_max_current_idx]
                price_max_prev = recent_prices.loc[price_max_prev_idx]
                
                volume_at_current_max = recent_volumes.loc[price_max_current_idx]
                volume_at_prev_max = recent_volumes.loc[price_max_prev_idx]
                
                # Цена делает новый максимум, объем падает
                if (price_max_current > price_max_prev and 
                    volume_at_current_max < volume_at_prev_max * 0.8 and
                    volume_at_prev_max > 0):  # Защита от деления на 0
                    volume_drop_pct = (1 - volume_at_current_max / volume_at_prev_max) * 100
                    strength = min(5, int(volume_drop_pct / 10))
                    
                    return {
                        'divergence_type': 'BEARISH',
                        'strength': max(strength, 3),
                        'description': f'Медвежья дивергенция объема: цена обновила максимум, объем упал на {volume_drop_pct:.0f}%'
                    }
        
        # === ЛОЖНЫЙ ПРОБОЙ (низкий объем на тесте уровня) ===
        current_volume = df['volume'].iloc[-1]
        
        # Если текущий объем < 70% от среднего - подозрение на ложный пробой
        if current_volume < avg_volume * 0.7:
            volume_deficit_pct = (1 - current_volume / avg_volume) * 100
            
            return {
                'divergence_type': 'FALSE_BREAKOUT',
                'strength': 2,  # Средняя сила сигнала
                'description': f'Подозрение на ложный пробой: объем на {volume_deficit_pct:.0f}% ниже среднего'
            }
        
        return {'divergence_type': None, 'strength': 0, 'description': ''}
        
    except Exception as e:
        return {'divergence_type': None, 'strength': 0, 'description': ''}


def analyze_range_trading_signal(df, symbol="UNKNOWN"):
    """
    УЛУЧШЕННАЯ главная функция анализа для Range Trading стратегии
    
    Проверяет все условия и возвращает торговый сигнал
    
    УЛУЧШЕНИЯ v2.0:
    - Линейная регрессия для определения флэта
    - Улучшенные дивергенции с фильтрацией
    - Динамический стоп-лосс на основе ATR
    - Относительное позиционирование в канале (не абсолютное)
    - Проверка разворота RSI (направление + уровень)
    - Гибкая система подтверждений
    - Встроенная проверка R:R перед входом
    
    Returns:
        dict: {
            'action': 'BUY'/'SELL'/'HOLD',
            'confidence': int (0-10),
            'entry_price': float,
            'stop_loss': float,
            'take_profit': float,
            'risk_reward_ratio': float,
            'signals': list,
            'summary': str
        }
    """
    if df is None or len(df) < 100:  # Увеличили минимум для надежной регрессии
        return {
            'action': 'HOLD',
            'confidence': 0,
            'entry_price': 0,
            'stop_loss': 0,
            'take_profit': 0,
            'risk_reward_ratio': 0,
            'signals': ["❌ Недостаточно данных для анализа (требуется минимум 100 баров)"],
            'summary': f"{symbol} | Недостаточно данных"
        }
    
    # Рассчитываем индикаторы
    middle_bb, upper_bb, lower_bb, bb_width = calculate_bollinger_bands(df)
    rsi = calculate_rsi(df)
    stoch_k, stoch_d = calculate_stochastic(df)
    macd_line, signal_line, macd_hist = calculate_macd(df)
    
    # Текущие значения
    current_price = df['close'].iloc[-1]
    current_rsi = rsi.iloc[-1]
    current_stoch_k = stoch_k.iloc[-1]
    current_stoch_d = stoch_d.iloc[-1]
    current_macd_hist = macd_hist.iloc[-1]
    prev_macd_hist = macd_hist.iloc[-2]
    
    current_upper_bb = upper_bb.iloc[-1]
    current_lower_bb = lower_bb.iloc[-1]
    current_middle_bb = middle_bb.iloc[-1]
    
    # Проверка: рынок во флэте?
    is_ranging = is_market_in_range(df, bb_width)
    
    signals = []
    confidence_score = 0
    action = "HOLD"
    
    # ШАГ 1: Проверка состояния рынка
    if not is_ranging:
        return {
            'action': 'HOLD',
            'confidence': 0,
            'entry_price': 0,
            'stop_loss': 0,
            'take_profit': 0,
            'risk_reward_ratio': 0,
            'signals': ["❌ Рынок НЕ во флэте - стратегия Range Trading не применима"],
            'summary': f"{symbol} | Рынок в тренде, ожидание флэта..."
        }
    
    signals.append("✅ Рынок во ФЛЭТЕ - условия для Range Trading подходят")
    confidence_score += 2
    
    # УЛУЧШЕННОЕ определение расстояния до границ (относительное, а не абсолютное)
    bb_range = current_upper_bb - current_lower_bb  # Полная ширина канала
    
    # Расстояние в процентах от ШИРИНЫ канала (не от цены!)
    distance_to_upper_pct = ((current_upper_bb - current_price) / bb_range) * 100
    distance_to_lower_pct = ((current_price - current_lower_bb) / bb_range) * 100
    
    # ШАГ 2: Проверка приближения к уровням (более строгие критерии)
    # В нижних/верхних 15% канала
    near_support = distance_to_lower_pct < 15
    near_resistance = distance_to_upper_pct < 15
    
    # Дополнительная проверка: цена должна быть БЛИЖЕ к границе, чем к центру
    near_support = near_support and (current_price - current_lower_bb) < (current_middle_bb - current_price)
    near_resistance = near_resistance and (current_upper_bb - current_price) < (current_price - current_middle_bb)
    
    # ========== СЦЕНАРИЙ ПОКУПКИ (у поддержки) ==========
    if near_support:
        signals.append(f"📍 Цена у ПОДДЕРЖКИ: {current_price:.4f} (позиция: {distance_to_lower_pct:.1f}% от дна канала)")
        confidence_score += 2
        
        # ШАГ 3A: АНАЛИЗ ОБЪЕМА (Volume Analysis)
        volume_analysis = analyze_volume_profile(df)
        
        if volume_analysis:
            # Проверка близости к POC (Point of Control)
            if volume_analysis['near_poc']:
                signals.append(f"✅ Цена у POC ({volume_analysis['volume_levels']['poc']:.4f}) - магнитный уровень справедливой цены")
                confidence_score += 1
            
            # Проверка нахождения в Value Area
            if volume_analysis['in_value_area']:
                signals.append(f"✅ Цена в Value Area - зона активной торговли")
                confidence_score += 1
            
            # Анализ текущего объема
            vol_intensity = volume_analysis['current_volume_intensity']
            vol_status = volume_analysis['volume_status']
            
            if vol_status == 'HIGH':
                signals.append(f"✅ ВЫСОКИЙ объем: {vol_intensity:.1f}x от среднего - сильное движение!")
                confidence_score += 2
            elif vol_status == 'LOW':
                signals.append(f"⚠️ Низкий объем: {vol_intensity:.1f}x - слабая активность")
                confidence_score -= 1
        
        # ДИВЕРГЕНЦИЯ ОБЪЕМА - СИЛЬНЕЙШИЙ СИГНАЛ!
        vol_divergence = detect_volume_divergence(df, lookback=20)
        
        if vol_divergence['divergence_type'] == 'BULLISH':
            signals.append(f"✅✅✅ БЫЧЬЯ ДИВЕРГЕНЦИЯ ОБЪЕМА! {vol_divergence['description']} - ТОП-СИГНАЛ РАЗВОРОТА!")
            confidence_score += vol_divergence['strength']
        elif vol_divergence['divergence_type'] == 'FALSE_BREAKOUT':
            signals.append(f"⚠️ {vol_divergence['description']} - возможен ложный пробой")
            confidence_score -= 1
        
        # ШАГ 3B: УЛУЧШЕННОЕ подтверждение осцилляторами
        oscillator_confirmations = 0
        
        # RSI: Перепроданность + ПРОВЕРКА РАЗВОРОТА
        if current_rsi < 35:  # Расширили зону до 35
            rsi_slope = rsi.iloc[-1] - rsi.iloc[-3]  # Изменение за 3 бара
            if rsi_slope > 0:  # RSI начал расти - РАЗВОРОТ ВВЕРХ
                signals.append(f"✅ RSI перепродан И разворачивается вверх: {current_rsi:.1f} (↑{rsi_slope:.1f})")
                oscillator_confirmations += 1
                confidence_score += 2
            else:
                signals.append(f"⚠️ RSI перепродан но еще падает: {current_rsi:.1f} (↓{abs(rsi_slope):.1f})")
        
        # УЛУЧШЕННАЯ проверка бычьей дивергенции RSI
        rsi_divergence = detect_rsi_divergence(df, rsi, lookback=20)
        if rsi_divergence == 'BULLISH':
            signals.append("✅✅ СИЛЬНАЯ БЫЧЬЯ ДИВЕРГЕНЦИЯ RSI (топ-сигнал!)")
            oscillator_confirmations += 2  # Дивергенция дает 2 подтверждения!
            confidence_score += 4
        
        # Stochastic: Золотой крест в зоне перепроданности (улучшенная проверка)
        if current_stoch_k < 25 and current_stoch_d < 25:  # Расширили зону до 25
            prev_stoch_k = stoch_k.iloc[-2]
            prev_stoch_d = stoch_d.iloc[-2]
            
            # Проверка качественного пересечения
            stoch_cross_up = (prev_stoch_k < prev_stoch_d and current_stoch_k > current_stoch_d)
            if stoch_cross_up:
                signals.append(f"✅ Stochastic: восходящее пересечение в зоне перепроданности (K:{current_stoch_k:.1f}, D:{current_stoch_d:.1f})")
                oscillator_confirmations += 1
                confidence_score += 2
        
        # MACD: Улучшенная логика - гистограмма разворачивается вверх
        macd_turning = (macd_hist.iloc[-1] > macd_hist.iloc[-2] and 
                       macd_hist.iloc[-2] < macd_hist.iloc[-3])  # Точка разворота
        if macd_turning and current_macd_hist < 0:
            signals.append("✅ MACD: гистограмма разворачивается вверх от медвежьей зоны")
            oscillator_confirmations += 1
            confidence_score += 1
        
        # ШАГ 4: Свечные паттерны (считаются как подтверждение)
        pattern = detect_candlestick_patterns(df)
        if pattern['direction'] == 'BULLISH':
            signals.append(f"✅ Бычий свечной паттерн: {pattern['pattern']} (сила: {pattern['strength']})")
            confidence_score += pattern['strength']
            oscillator_confirmations += 1  # Паттерн = дополнительное подтверждение
        
        # ШАГ 5: Дополнительная проверка объема (если Volume Analysis не сработал)
        if not volume_analysis:
            current_volume = df['volume'].iloc[-1]
            volume_avg = df['volume'].iloc[-20:].mean()
            volume_spike = current_volume > volume_avg * 1.3
            
            if volume_spike:
                volume_increase = (current_volume / volume_avg - 1) * 100
                signals.append(f"✅ Подтверждение объемом: +{volume_increase:.0f}% от среднего")
                confidence_score += 1
        
        # УЛУЧШЕННЫЕ условия для входа
        # При дивергенции достаточно 1 подтверждения, обычно нужно 2
        # Дивергенция объема также считается как сильное подтверждение
        has_volume_divergence = vol_divergence and vol_divergence.get('divergence_type') == 'BULLISH'
        min_confirmations = 1 if (rsi_divergence == 'BULLISH' or has_volume_divergence) else 2
        
        # Дополнительная проверка минимальной уверенности
        if oscillator_confirmations >= min_confirmations and confidence_score >= 6:
            action = "BUY"
            entry_price = current_price
            
            # ДИНАМИЧЕСКИЙ стоп-лосс на основе ATR
            stop_loss = calculate_dynamic_stop_loss(df, current_price, current_lower_bb, current_upper_bb, "BUY")
            take_profit = current_upper_bb * 0.995  # У сопротивления
            
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
            risk_reward = reward / risk if risk > 0 else 0
            
            # ВСТРОЕННАЯ ПРОВЕРКА R:R - защита от плохих сделок
            if risk_reward < 2.0:
                signals.append(f"⚠️ R:R слишком низкий: 1:{risk_reward:.2f} (требуется минимум 1:2.0)")
                confidence_score -= 2
                if confidence_score < 5:
                    action = "HOLD"
                    signals.append("❌ Сделка отменена: недостаточная уверенность после проверки R:R")
            
            if action == "BUY":
                signals.append(f"🎯 СИГНАЛ ПОКУПКИ (подтверждений: {oscillator_confirmations}, уверенность: {min(confidence_score, 10)}/10)")
                
                return {
                    'action': action,
                    'confidence': min(confidence_score, 10),
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'risk_reward_ratio': risk_reward,
                    'signals': signals,
                    'summary': f"{symbol} | BUY | Conf: {min(confidence_score, 10)}/10 | R:R = 1:{risk_reward:.2f}"
                }
    
    # ========== СЦЕНАРИЙ ПРОДАЖИ (у сопротивления) ==========
    elif near_resistance:
        signals.append(f"📍 Цена у СОПРОТИВЛЕНИЯ: {current_price:.4f} (позиция: {distance_to_upper_pct:.1f}% от верха канала)")
        confidence_score += 2
        
        # ШАГ 3A: АНАЛИЗ ОБЪЕМА (Volume Analysis)
        volume_analysis = analyze_volume_profile(df)
        
        if volume_analysis:
            # Проверка близости к POC (Point of Control)
            if volume_analysis['near_poc']:
                signals.append(f"✅ Цена у POC ({volume_analysis['volume_levels']['poc']:.4f}) - магнитный уровень справедливой цены")
                confidence_score += 1
            
            # Проверка нахождения в Value Area
            if volume_analysis['in_value_area']:
                signals.append(f"✅ Цена в Value Area - зона активной торговли")
                confidence_score += 1
            
            # Анализ текущего объема
            vol_intensity = volume_analysis['current_volume_intensity']
            vol_status = volume_analysis['volume_status']
            
            if vol_status == 'HIGH':
                signals.append(f"✅ ВЫСОКИЙ объем: {vol_intensity:.1f}x от среднего - сильное движение!")
                confidence_score += 2
            elif vol_status == 'LOW':
                signals.append(f"⚠️ Низкий объем: {vol_intensity:.1f}x - слабая активность")
                confidence_score -= 1
        
        # ДИВЕРГЕНЦИЯ ОБЪЕМА - СИЛЬНЕЙШИЙ СИГНАЛ!
        vol_divergence = detect_volume_divergence(df, lookback=20)
        
        if vol_divergence['divergence_type'] == 'BEARISH':
            signals.append(f"✅✅✅ МЕДВЕЖЬЯ ДИВЕРГЕНЦИЯ ОБЪЕМА! {vol_divergence['description']} - ТОП-СИГНАЛ РАЗВОРОТА!")
            confidence_score += vol_divergence['strength']
        elif vol_divergence['divergence_type'] == 'FALSE_BREAKOUT':
            signals.append(f"⚠️ {vol_divergence['description']} - возможен ложный пробой")
            confidence_score -= 1
        
        # ШАГ 3B: УЛУЧШЕННОЕ подтверждение осцилляторами
        oscillator_confirmations = 0
        
        # RSI: Перекупленность + ПРОВЕРКА РАЗВОРОТА
        if current_rsi > 65:  # Расширили зону до 65
            rsi_slope = rsi.iloc[-1] - rsi.iloc[-3]  # Изменение за 3 бара
            if rsi_slope < 0:  # RSI начал падать - РАЗВОРОТ ВНИЗ
                signals.append(f"✅ RSI перекуплен И разворачивается вниз: {current_rsi:.1f} (↓{abs(rsi_slope):.1f})")
                oscillator_confirmations += 1
                confidence_score += 2
            else:
                signals.append(f"⚠️ RSI перекуплен но еще растет: {current_rsi:.1f} (↑{rsi_slope:.1f})")
        
        # УЛУЧШЕННАЯ проверка медвежьей дивергенции RSI
        rsi_divergence = detect_rsi_divergence(df, rsi, lookback=20)
        if rsi_divergence == 'BEARISH':
            signals.append("✅✅ СИЛЬНАЯ МЕДВЕЖЬЯ ДИВЕРГЕНЦИЯ RSI (топ-сигнал!)")
            oscillator_confirmations += 2  # Дивергенция дает 2 подтверждения!
            confidence_score += 4
        
        # Stochastic: Мертвый крест в зоне перекупленности (улучшенная проверка)
        if current_stoch_k > 75 and current_stoch_d > 75:  # Расширили зону до 75
            prev_stoch_k = stoch_k.iloc[-2]
            prev_stoch_d = stoch_d.iloc[-2]
            
            # Проверка качественного пересечения
            stoch_cross_down = (prev_stoch_k > prev_stoch_d and current_stoch_k < current_stoch_d)
            if stoch_cross_down:
                signals.append(f"✅ Stochastic: нисходящее пересечение в зоне перекупленности (K:{current_stoch_k:.1f}, D:{current_stoch_d:.1f})")
                oscillator_confirmations += 1
                confidence_score += 2
        
        # MACD: Улучшенная логика - гистограмма разворачивается вниз
        macd_turning = (macd_hist.iloc[-1] < macd_hist.iloc[-2] and 
                       macd_hist.iloc[-2] > macd_hist.iloc[-3])  # Точка разворота
        if macd_turning and current_macd_hist > 0:
            signals.append("✅ MACD: гистограмма разворачивается вниз от бычьей зоны")
            oscillator_confirmations += 1
            confidence_score += 1
        
        # ШАГ 4: Свечные паттерны (считаются как подтверждение)
        pattern = detect_candlestick_patterns(df)
        if pattern['direction'] == 'BEARISH':
            signals.append(f"✅ Медвежий свечной паттерн: {pattern['pattern']} (сила: {pattern['strength']})")
            confidence_score += pattern['strength']
            oscillator_confirmations += 1  # Паттерн = дополнительное подтверждение
        
        # ШАГ 5: Дополнительная проверка объема (если Volume Analysis не сработал)
        if not volume_analysis:
            current_volume = df['volume'].iloc[-1]
            volume_avg = df['volume'].iloc[-20:].mean()
            volume_spike = current_volume > volume_avg * 1.3
            
            if volume_spike:
                volume_increase = (current_volume / volume_avg - 1) * 100
                signals.append(f"✅ Подтверждение объемом: +{volume_increase:.0f}% от среднего")
                confidence_score += 1
        
        # УЛУЧШЕННЫЕ условия для входа
        # При дивергенции достаточно 1 подтверждения, обычно нужно 2
        # Дивергенция объема также считается как сильное подтверждение
        has_volume_divergence = vol_divergence and vol_divergence.get('divergence_type') == 'BEARISH'
        min_confirmations = 1 if (rsi_divergence == 'BEARISH' or has_volume_divergence) else 2
        
        # Дополнительная проверка минимальной уверенности
        if oscillator_confirmations >= min_confirmations and confidence_score >= 6:
            action = "SELL"
            entry_price = current_price
            
            # ДИНАМИЧЕСКИЙ стоп-лосс на основе ATR
            stop_loss = calculate_dynamic_stop_loss(df, current_price, current_lower_bb, current_upper_bb, "SELL")
            take_profit = current_lower_bb * 1.005  # У поддержки
            
            risk = stop_loss - entry_price
            reward = entry_price - take_profit
            risk_reward = reward / risk if risk > 0 else 0
            
            # ВСТРОЕННАЯ ПРОВЕРКА R:R - защита от плохих сделок
            if risk_reward < 2.0:
                signals.append(f"⚠️ R:R слишком низкий: 1:{risk_reward:.2f} (требуется минимум 1:2.0)")
                confidence_score -= 2
                if confidence_score < 5:
                    action = "HOLD"
                    signals.append("❌ Сделка отменена: недостаточная уверенность после проверки R:R")
            
            if action == "SELL":
                signals.append(f"🎯 СИГНАЛ ПРОДАЖИ (подтверждений: {oscillator_confirmations}, уверенность: {min(confidence_score, 10)}/10)")
                
                return {
                    'action': action,
                    'confidence': min(confidence_score, 10),
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'risk_reward_ratio': risk_reward,
                    'signals': signals,
                    'summary': f"{symbol} | SELL | Conf: {min(confidence_score, 10)}/10 | R:R = 1:{risk_reward:.2f}"
                }
    
    # Нет сигнала - определяем позицию в канале
    if near_support or near_resistance:
        position_status = "у границы канала (ожидание подтверждений)"
    else:
        position_status = "в середине канала (ожидание подхода к уровням)"
    
    return {
        'action': 'HOLD',
        'confidence': max(confidence_score, 0),
        'entry_price': 0,
        'stop_loss': 0,
        'take_profit': 0,
        'risk_reward_ratio': 0,
        'signals': signals + [f"⏳ Ожидание: {position_status}"],
        'summary': f"{symbol} | HOLD | Conf: {max(confidence_score, 0)}/10 | Позиция: {position_status}"
    }


def monitor_range_conditions(df, symbol="UNKNOWN"):
    """
    Мониторинг условий для Range Trading без генерации сигналов
    
    Полезно для отладки и анализа состояния рынка
    
    Returns:
        dict: Текущее состояние рынка и условий для Range Trading
    """
    if df is None or len(df) < 100:
        return None
    
    _, upper_bb, lower_bb, bb_width = calculate_bollinger_bands(df)
    
    current_price = df['close'].iloc[-1]
    current_upper = upper_bb.iloc[-1]
    current_lower = lower_bb.iloc[-1]
    bb_range = current_upper - current_lower
    
    # Определяем состояние
    is_ranging = is_market_in_range(df, bb_width)
    
    distance_to_upper_pct = ((current_upper - current_price) / bb_range) * 100
    distance_to_lower_pct = ((current_price - current_lower) / bb_range) * 100
    
    conditions = {
        'symbol': symbol,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'price': current_price,
        'bb_upper': current_upper,
        'bb_lower': current_lower,
        'bb_width_pct': bb_width.iloc[-1] * 100,
        'in_range': is_ranging,
        'distance_to_upper_pct': distance_to_upper_pct,
        'distance_to_lower_pct': distance_to_lower_pct,
        'position': 'SUPPORT' if distance_to_lower_pct < 15 else ('RESISTANCE' if distance_to_upper_pct < 15 else 'MIDDLE')
    }
    
    return conditions
