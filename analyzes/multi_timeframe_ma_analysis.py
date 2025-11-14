import pandas as pd
from datetime import datetime
import os
from analyzes.atr_rsi_stochastic import (calculate_atr, calculate_rsi, calculate_stochastic)


LOGS_DIR = "logs"

def log_to_file(filename, text):
    # Создаём папку logs, если её нет
    os.makedirs(LOGS_DIR, exist_ok=True)
    full_path = os.path.join(LOGS_DIR, filename)
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(text)

def calculate_sma(data, period):
    """Рассчитывает SMA для заданного периода"""
    if isinstance(data, pd.DataFrame):
        return data['close'].rolling(window=period).mean()
    else:
        return data.rolling(window=period).mean()

def calculate_ema(data, period):
    """Рассчитывает EMA для заданного периода"""
    if isinstance(data, pd.DataFrame):
        return data['close'].ewm(span=period, adjust=False).mean()
    else:
        return data.ewm(span=period, adjust=False).mean()

def calculate_distance_stats(df, fast_col, slow_col, lookback_periods):
    """
    Рассчитывает статистику расстояния между двумя скользящими средними.
    fast_col, slow_col — названия столбцов с быстрыми и медленными средними.
    """
    df_clean = df.dropna(subset=[fast_col, slow_col]).copy()
    df_clean['distance_pct'] = ((df_clean[fast_col] - df_clean[slow_col]) / df_clean[slow_col]) * 100
    recent_data = df_clean['distance_pct'].tail(lookback_periods)
    if recent_data.empty:
        return None, None, None, None, None
    mean_distance = recent_data.mean()
    std_distance = recent_data.std()
    max_distance = recent_data.max()
    min_distance = recent_data.min()
    current_distance = df_clean['distance_pct'].iloc[-1]
    return current_distance, mean_distance, std_distance, max_distance, min_distance

def analyze_price_vs_ma(df, ma_period=200, ma_type="EMA", volatility_multiplier=1.0):
    """
    Анализирует положение цены относительно ключевой скользящей средней.
    
    Args:
        df: DataFrame с данными OHLCV
        ma_period: Период скользящей средней
        ma_type: Тип MA ("EMA" или "SMA")
        volatility_multiplier: Множитель для порога волатильности
    
    Returns:
        tuple: (позиция, расстояние_%, описание_силы)
    """
    STD_PERIOD = 14
    
    # Расчет MA
    ma_value = (calculate_ema(df, ma_period) if ma_type == "EMA" 
                else calculate_sma(df, ma_period)).iloc[-1]
    
    current_price = df['close'].iloc[-1]
    price_distance_pct = ((current_price - ma_value) / ma_value) * 100
    
    # Расчет адаптивного порога уверенности
    atr = df['close'].rolling(STD_PERIOD).std().iloc[-1]
    if pd.isna(atr) or atr == 0:
        atr = df['close'].std()
    
    confidence_threshold = (atr / current_price * 100) * volatility_multiplier
    
    # Определение силы и направления
    is_above = price_distance_pct > 0
    is_strong = abs(price_distance_pct) > confidence_threshold
    
    position = "ABOVE" if is_above else "BELOW"
    strength = "Уверенно" if is_strong else "Слабо"
    direction = "выше" if is_above else "ниже"
    
    return position, price_distance_pct, f"{strength} {direction}"

def generate_trading_verdict(is_above, is_below, ma_signal):
    """Генерирует торговый вердикт на основе положения цены и сигнала MA"""
    if is_above and ma_signal in ["BUY", "BULLISH"]:
        return "STRONG_BUY"
    elif is_below and ma_signal in ["SELL", "BEARISH"]: 
        return "STRONG_SELL"
    elif is_above:
        return "CAUTIOUS_BUY"  # цена выше, но MA не подтверждают
    elif is_below:
        return "CAUTIOUS_SELL" # цена ниже, но MA не подтверждают
    else:
        return "NEUTRAL_WAIT"

def analyze_ma_signals(df, fast_period, slow_period, lookback_periods, symbol="UNKNOWN", ma_type="SMA"):
    """
    Анализирует сигналы по SMA или EMA.
    
    Args:
        df: DataFrame с данными OHLCV
        fast_period: Период быстрой MA
        slow_period: Период медленной MA
        lookback_periods: Период для анализа истории
        symbol: Название инструмента
        ma_type: Тип MA ("SMA" или "EMA")
    
    Returns:
        dict: Словарь с результатами анализа или None при недостатке данных
    """
    # Ранняя проверка данных
    if len(df) < 2:
        return None
    
    if ma_type not in ("SMA", "EMA"):
        raise ValueError("ma_type должен быть 'SMA' или 'EMA'")
    
    log_filename = f"{ma_type.lower()}_analysis_log.txt"
    fast_col = f"{ma_type.lower()}_fast"
    slow_col = f"{ma_type.lower()}_slow"
    
    # Расчет MA
    calculate_func = calculate_sma if ma_type == "SMA" else calculate_ema
    df[fast_col] = calculate_func(df, fast_period)
    df[slow_col] = calculate_func(df, slow_period)
    
    # Проверка статистики
    stats = calculate_distance_stats(df, fast_col, slow_col, lookback_periods)
    if stats[0] is None:
        log_to_file(log_filename, 
                   f"{datetime.now()} | {symbol} | Недостаточно данных для анализа {ma_type}\n")
        return None
    
    current_dist, mean_dist, std_dist, max_dist, min_dist = stats
    
    current_fast = df[fast_col].iloc[-1]
    current_slow = df[slow_col].iloc[-1]
    previous_fast = df[fast_col].iloc[-2]
    previous_slow = df[slow_col].iloc[-2]

    # Анализ относительно MA200 (самый важный уровень) - используем тот же тип что и основной анализ
    price_vs_ma200_signal, ma200_dist, ma200_strength = analyze_price_vs_ma(df, 200, ma_type)
    
    # Анализ относительно MA50 (второй по важности) - используем тот же тип что и основной анализ
    price_vs_ma50_signal, ma50_dist, ma50_strength = analyze_price_vs_ma(df, 50, ma_type)

    # ФОРМИРУЕМ ОБЩУЮ КАРТИНУ
    price_position_text = f"Цена: {ma200_strength} {ma_type}200 ({ma200_dist:+.2f}%), {ma50_strength} {ma_type}50 ({ma50_dist:+.2f}%)"
    
    # КРИТЕРИЙ "УВЕРЕННОЙ ТОРГОВЛИ ВЫШЕ"
    is_confidently_above = (price_vs_ma200_signal == "ABOVE" and ma200_strength == "Уверенно выше")

    # КРИТЕРИЙ "УВЕРЕННОЙ ТОРГОВЛИ НИЖЕ"
    is_confidently_below = (price_vs_ma200_signal == "BELOW" and ma200_strength == "Уверенно ниже")

    # Определение пересечения MA (crossover)
    has_bullish_cross = (previous_fast < previous_slow and current_fast > current_slow)
    has_bearish_cross = (previous_fast > previous_slow and current_fast < current_slow)
    
    if has_bullish_cross:
        crossover_signal = "BUY"
        signal_name = "Золотой крест" if ma_type == "SMA" else "Bullish EMA crossover"
        crossover_text = f"СИГНАЛ ПОКУПКИ: {signal_name}"
    elif has_bearish_cross:
        crossover_signal = "SELL"
        signal_name = "Мертвый крест" if ma_type == "SMA" else "Bearish EMA crossover"
        crossover_text = f"СИГНАЛ ПРОДАЖИ: {signal_name}"
    else:
        crossover_signal = "NEUTRAL"
        crossover_text = f"Пересечения {ma_type} нет"
    # Анализ силы тренда
    CONFIDENCE_MULTIPLIER = 0.5
    DEFAULT_THRESHOLD = 0.1
    
    ma_slope = current_fast - previous_fast
    confidence_threshold = (std_dist * CONFIDENCE_MULTIPLIER 
                           if std_dist and not pd.isna(std_dist) 
                           else DEFAULT_THRESHOLD)
    
    is_bullish_trend = (current_dist > confidence_threshold and ma_slope > 0)
    is_bearish_trend = (current_dist < -confidence_threshold and ma_slope < 0)
    
    if is_bullish_trend:
        strength_signal = "BULLISH"
        strength_text = f" | Уверенный бычий тренд (расстояние: {current_dist:+.2f}%)"
    elif is_bearish_trend:
        strength_signal = "BEARISH"
        strength_text = f" | Уверенный медвежий тренд (расстояние: {current_dist:+.2f}%)"
    else:
        strength_signal = "NEUTRAL"
        strength_text = " | Тренд неопределенный/консолидация"

    # Формирование финального сигнала
    final_signal = crossover_signal if crossover_signal != "NEUTRAL" else strength_signal
    final_text = (crossover_text + strength_text if crossover_signal != "NEUTRAL" 
                  else f"Сигнал по {ma_type}: {strength_signal}" + strength_text)

    # Расчет прогресс-бара для визуализации расстояния
    BAR_LENGTH = 20
    range_width = max_dist - min_dist
    
    if range_width > 0:
        normalized_position = (current_dist - min_dist) / range_width
        position_index = int(normalized_position * BAR_LENGTH)
    else:
        position_index = BAR_LENGTH // 2
    
    progress_bar = f"[{'=' * position_index}|{'=' * (BAR_LENGTH - position_index - 1)}]"

    return {
        'bar': f"Текущее расстояние: {current_dist:+.2f}% {progress_bar}",
        'signal': f"{final_text}",
        'price_position': price_position_text,
        'is_confidently_above_ema200': is_confidently_above,
        'is_confidently_below_ema200': is_confidently_below,
        'trading_verdict': generate_trading_verdict(is_confidently_above, is_confidently_below, final_signal)
    }

def calculate_bollinger_bands_1D(df, period=20, num_std=2, ma_type="EMA", symbol="UNKNOWN", trend_direction="NEUTRAL"):
    """
    Улучшенная реализация для дневного таймфрейма.
    Добавлен аргумент trend_direction для учета глобального тренда.
    """
    df = df.copy()
    # ... (ваш расчет полос остается без изменений) ...
    if ma_type == "EMA":
        df['bb_middle'] = df['close'].ewm(span=period, adjust=False).mean()
    else:
        df['bb_middle'] = df['close'].rolling(window=period).mean()
    df['bb_std'] = df['close'].rolling(window=period).std()
    df['bb_upper'] = df['bb_middle'] + num_std * df['bb_std']
    df['bb_lower'] = df['bb_middle'] - num_std * df['bb_std']

    # УЛУЧШЕННАЯ ГЕНЕРАЦИЯ СИГНАЛОВ ДЛЯ 1D
    df['bb_signal'] = "NEUTRAL"

    # Логика с учетом тренда
    if trend_direction == "BUY":
        # В бычьем тренде нас интересуют отскоки ОТ СРЕДНЕЙ ЛИНИИ или НИЖНЕЙ ПОЛОСЫ
        df.loc[df['close'] < df['bb_middle'], 'bb_signal'] = "BUY DIP" # Сигнал к покупке на откате
        df.loc[df['close'] < df['bb_lower'], 'bb_signal'] = "STRONG BUY DIP" # Сильный откат, хорошая возможность

    elif trend_direction == "SELL":
        # В медвежьем тренде нас интересуют отскоки ОТ СРЕДНЕЙ ЛИНИИ или ВЕРХНЕЙ ПОЛОСЫ
        df.loc[df['close'] > df['bb_middle'], 'bb_signal'] = "SELL RALLY" # Сигнал к продаже на отскоке
        df.loc[df['close'] > df['bb_upper'], 'bb_signal'] = "STRONG SELL RALLY" # Сильный отскок, хорошая возможность

    else:
        # Если тренд не определен, используем старую логику (но она рискованна)
        df.loc[df['close'] > df['bb_upper'], 'bb_signal'] = "OVERBOUGHT"
        df.loc[df['close'] < df['bb_lower'], 'bb_signal'] = "OVERSOLD"

    return df

def calculate_bollinger_bands(df, period=20, num_std=2, ma_type="SMA", symbol="UNKNOWN"):
    """
    Сложная реализация полос Боллинджера с выбором типа средней и генерацией сигналов.
    Возвращает DataFrame с границами и сигналами.
    Логирует последний сигнал.
    """
    df = df.copy()
    if ma_type == "EMA":
        df['bb_middle'] = df['close'].ewm(span=period, adjust=False).mean()
    else:
        df['bb_middle'] = df['close'].rolling(window=period).mean()
    df['bb_std'] = df['close'].rolling(window=period).std()
    df['bb_upper'] = df['bb_middle'] + num_std * df['bb_std']
    df['bb_lower'] = df['bb_middle'] - num_std * df['bb_std']

    # Генерация сигналов
    df['bb_signal'] = "NEUTRAL"
    df.loc[df['close'] > df['bb_upper'], 'bb_signal'] = "SELL"
    df.loc[df['close'] < df['bb_lower'], 'bb_signal'] = "BUY"

    # Логирование последнего сигнала
    last_row = df.iloc[-1]
    log_str = (
        f"{datetime.now()} | {symbol} | Bollinger Bands | {ma_type}\n"
        f"Период: {period}, Стд: {num_std}\n"
        f"Цена: {last_row['close']:.2f}\n"
        f"BB_middle: {last_row['bb_middle']:.2f}\n"
        f"BB_upper: {last_row['bb_upper']:.2f}\n"
        f"BB_lower: {last_row['bb_lower']:.2f}\n"
        f"Сигнал: {last_row['bb_signal']}\n"
        f"---\n"
    )
    log_to_file("bollinger_bands_log.txt", log_str)

    return df[['bb_middle', 'bb_upper', 'bb_lower', 'bb_signal']]

def calculate_macd(df, fast_period=12, slow_period=26, signal_period=9, symbol="UNKNOWN"):
    """
    Рассчитывает MACD и сигнальную линию.
    
    Args:
        df: DataFrame с данными OHLCV (требуется столбец 'close')
        fast_period: Период быстрой EMA (по умолчанию 12)
        slow_period: Период медленной EMA (по умолчанию 26)
        signal_period: Период сигнальной линии (по умолчанию 9)
        symbol: Название инструмента для логирования
    
    Returns:
        DataFrame с колонками 'macd', 'macd_signal', 'macd_hist' и attrs с сигналом
    """
    # Проверка на достаточность данных
    if len(df) < 2:
        return pd.DataFrame({'macd': [], 'macd_signal': [], 'macd_hist': []})
    
    # Расчёт MACD компонентов
    ema_fast = df['close'].ewm(span=fast_period, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow_period, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal_period, adjust=False).mean()
    macd_hist = macd - macd_signal

    # Извлечение текущих и предыдущих значений
    last_macd, prev_macd = macd.iloc[-1], macd.iloc[-2]
    last_signal, prev_signal = macd_signal.iloc[-1], macd_signal.iloc[-2]
    last_hist, prev_hist = macd_hist.iloc[-1], macd_hist.iloc[-2]

    # Анализ сигналов
    signal, details, action = _analyze_macd_signals(
        last_macd, last_signal, last_hist,
        prev_macd, prev_signal, prev_hist
    )

    # Логирование
    # _log_macd_analysis(symbol, last_macd, last_signal, last_hist, signal, details, action)

    # Формирование результата
    result = pd.DataFrame({
        'macd': macd,
        'macd_signal': macd_signal,
        'macd_hist': macd_hist
    })

    # Сохранение метаданных
    try:
        result.attrs['summary_signal'] = signal
        result.attrs['summary_details'] = ', '.join(details)
        result.attrs['action'] = action  # Итоговое действие: BUY/SELL/WAIT
    except (AttributeError, TypeError):
        pass  # Старые версии pandas могут не поддерживать attrs

    return result


def _analyze_macd_signals(last_macd, last_signal, last_hist, prev_macd, prev_signal, prev_hist):
    """
    Вспомогательная функция для анализа MACD сигналов.
    
    Returns:
        tuple: (signal, details, action) - основной сигнал, список деталей анализа и итоговое действие
    """
    signal = "NEUTRAL"
    details = []
    
    # 1. Анализ положения относительно нуля
    both_above_zero = last_macd > 0 and last_signal > 0
    both_below_zero = last_macd < 0 and last_signal < 0
    
    if both_above_zero:
        details.append("Бычий тренд (выше нуля)")
    elif both_below_zero:
        details.append("Медвежий тренд (ниже нуля)")
    else:
        details.append("Переходная зона")
    
    # 2. Анализ пересечения линий (приоритет над расположением)
    has_bullish_cross = last_macd > last_signal and prev_macd <= prev_signal
    has_bearish_cross = last_macd < last_signal and prev_macd >= prev_signal
    
    if has_bullish_cross:
        signal = "BUY"
        details.append("ПЕРЕСЕЧЕНИЕ СНИЗУ ВВЕРХ")
    elif has_bearish_cross:
        signal = "SELL"
        details.append("ПЕРЕСЕЧЕНИЕ СВЕРХУ ВНИЗ")
    elif last_macd > last_signal:
        signal = "BULLISH"
        details.append("Бычье расположение")
    elif last_macd < last_signal:
        signal = "BEARISH"
        details.append("Медвежье расположение")
    
    # 3. Анализ гистограммы (импульс)
    hist_diff = last_hist - prev_hist
    hist_growing = hist_diff > 0
    hist_declining = hist_diff < 0
    
    if last_hist > 0:  # Положительная гистограмма
        if hist_growing:
            details.append("Импульс усиливается")
        elif hist_declining:
            details.append("Импульс ослабевает")
    else:  # Отрицательная гистограмма
        if hist_declining:
            details.append("Спад усиливается")
        elif hist_growing:
            details.append("Спад ослабевает")
    
    # 4. Формирование итогового действия (FINAL ACTION)
    action = _determine_macd_action(
        signal, both_above_zero, both_below_zero,
        has_bullish_cross, has_bearish_cross,
        last_hist, hist_growing, hist_declining
    )
    
    return signal, details, action


def _determine_macd_action(signal, both_above_zero, both_below_zero, 
                           has_bullish_cross, has_bearish_cross,
                           last_hist, hist_growing, hist_declining):
    """
    Определяет итоговое действие на основе всех MACD сигналов.
    
    Returns:
        str: "BUY", "SELL" или "WAIT"
    """
    # ОЧЕНЬ СИЛЬНЫЕ СИГНАЛЫ НА ПОКУПКУ
    if has_bullish_cross and both_above_zero and hist_growing:
        return "BUY"  # Идеальное бычье пересечение
    
    if has_bullish_cross and both_above_zero:
        return "BUY"  # Пересечение в бычьей зоне
    
    # СИЛЬНЫЕ СИГНАЛЫ НА ПОКУПКУ  
    if has_bullish_cross and last_hist > 0 and hist_growing:
        return "BUY"  # Пересечение с растущим импульсом
    
    if signal == "BULLISH" and both_above_zero and last_hist > 0 and hist_growing:
        return "BUY"  # Все факторы за покупку
    
    # ОЧЕНЬ СИЛЬНЫЕ СИГНАЛЫ НА ПРОДАЖУ
    if has_bearish_cross and both_below_zero and hist_declining:
        return "SELL"  # Идеальное медвежье пересечение
    
    if has_bearish_cross and both_below_zero:
        return "SELL"  # Пересечение в медвежьей зоне
    
    # СИЛЬНЫЕ СИГНАЛЫ НА ПРОДАЖУ
    if has_bearish_cross and last_hist < 0 and hist_declining:
        return "SELL"  # Пересечение с падающим импульсом
    
    if signal == "BEARISH" and both_below_zero and last_hist < 0 and hist_declining:
        return "SELL"  # Все факторы за продажу
    
    # КОНФЛИКТНЫЕ СИТУАЦИИ - ЖДАТЬ
    if both_above_zero and signal == "BEARISH":
        return "WAIT"  # Конфликт: бычий тренд но медвежий сигнал
    
    if both_below_zero and signal == "BULLISH":
        return "WAIT"  # Конфликт: медвежий тренд но бычий сигнал
    
    if has_bullish_cross and hist_declining:
        return "WAIT"  # Пересечение есть, но импульс слабый
    
    if has_bearish_cross and not hist_declining:
        return "WAIT"  # Пересечение есть, но спад ослабевает
    
    # УМЕРЕННЫЕ СИГНАЛЫ
    if signal == "BULLISH" and last_hist > 0:
        return "BUY"  # Умеренный бычий сигнал
    
    if signal == "BEARISH" and last_hist < 0:
        return "SELL"  # Умеренный медвежий сигнал
    
    # НЕЙТРАЛЬНЫЕ СИТУАЦИИ
    if signal == "NEUTRAL":
        return "WAIT"
    
    # ПО УМОЛЧАНИЮ - ОЖИДАНИЕ
    return "WAIT"


def _log_macd_analysis(symbol, last_macd, last_signal, last_hist, signal, details, action):
    """Вспомогательная функция для логирования MACD анализа."""
    position = "Выше нуля" if last_macd > 0 else "Ниже нуля"
    histogram = "Положительная" if last_hist > 0 else "Отрицательная"
    
    # Эмодзи для визуализации действия
    action_emoji = {
        "BUY": "🟢 ПОКУПАТЬ",
        "SELL": "🔴 ПРОДАВАТЬ",
        "WAIT": "🟡 ЖДАТЬ"
    }
    
    log_str = (
        f"{datetime.now()} | {symbol} | MACD АНАЛИЗ\n"
        f"MACD: {last_macd:.6f} | Signal: {last_signal:.6f} | Hist: {last_hist:.6f}\n"
        f"Положение: {position} | Гистограмма: {histogram}\n"
        f"СИГНАЛ: {signal} | Детали: {', '.join(details)}\n"
        f"⚡ ДЕЙСТВИЕ: {action_emoji.get(action, action)}\n"
        f"---\n"
    )
    log_to_file("macd_log.txt", log_str)
    
def analyze_volume(df, volume_ma_period=20, symbol="UNKNOWN"):
    """
    Анализирует торговый объем: сравнивает текущий объем с его скользящим средним.
    Возвращает словарь с результатами и сигналом.
    """
    if 'volume' not in df.columns or len(df) < volume_ma_period:
        return {
            "symbol": symbol,
            "current_volume": None,
            "avg_volume": None,
            "volume_ratio": None,
            "signal": "Недостаточно данных для анализа объема"
        }

    df = df.copy()
    df['volume_ma'] = df['volume'].rolling(window=volume_ma_period).mean()
    current_volume = df['volume'].iloc[-1]
    avg_volume = df['volume_ma'].iloc[-1]
    volume_ratio = current_volume / avg_volume if avg_volume else None

    # Определяем направление свечи
    current_close = df['close'].iloc[-1]
    current_open = df['open'].iloc[-1]
    is_bullish_candle = current_close > current_open

    # Определение сигнала - фиксируем движение (есть или нет)
    if volume_ratio is None:
        signal = "Недостаточно данных для анализа объема"
        action = "WAIT"
    elif volume_ratio > 2.0:
        # Высокий объем = движение есть
        signal = f"🚀 ВЫСОКИЙ ОБЪЕМ! Движение подтверждено"
        action = "BUY"
    elif volume_ratio < 0.5:
        # Низкий объем = движения нет
        signal = "⚠️ НИЗКИЙ ОБЪЕМ! Движение не подтверждено"
        action = "WAIT"
    else:
        # Нормальный объем = есть движение
        signal = "Обычный объем, движение присутствует"
        action = "BUY"

    # Логирование
    action_emoji = {
        "BUY": "🟢 ПОКУПАТЬ",
        "SELL": "🔴 ПРОДАВАТЬ",
        "WAIT": "🟡 ЖДАТЬ"
    }
    
    log_str = (
        f"{datetime.now()} | {symbol} | VOLUME\n"
        f"Объем: {current_volume:.0f} vs средний {avg_volume:.0f} (x{volume_ratio:.1f})\n"
        f"Сигнал: {signal}\n"
        f"⚡ ДЕЙСТВИЕ: {action_emoji.get(action, action)}\n"
        f"---\n"
    )
    # log_to_file("volume_analysis_log.txt", log_str)

    return {
        "symbol": symbol,
        "current_volume": current_volume,
        "avg_volume": avg_volume,
        "volume_ratio": volume_ratio,
        "signal": signal,
        "action": action,  # BUY/SELL/WAIT
        "log": log_str
    }

