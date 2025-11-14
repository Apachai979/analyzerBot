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
    return data['close'].rolling(window=period).mean()

def calculate_ema(data, period):
    """Рассчитывает EMA для заданного периода"""
    return data['close'].ewm(span=period, adjust=False).mean()

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

def analyze_ma_signals(df, fast_period, slow_period, lookback_periods, symbol="UNKNOWN", ma_type="SMA"):
    """
    Анализирует сигналы по SMA или EMA, записывает результат в файл.
    ma_type: "SMA" или "EMA"
    """
    log_filename = f"{ma_type.lower()}_analysis_log.txt"  
    fast_col = f"{ma_type.lower()}_fast"
    slow_col = f"{ma_type.lower()}_slow"

    if ma_type == "SMA":
        df[fast_col] = calculate_sma(df, fast_period)
        df[slow_col] = calculate_sma(df, slow_period)
    elif ma_type == "EMA":
        df[fast_col] = calculate_ema(df, fast_period)
        df[slow_col] = calculate_ema(df, slow_period)
    else:
        raise ValueError("ma_type должен быть 'SMA' или 'EMA'")

    stats = calculate_distance_stats(df, fast_col, slow_col, lookback_periods)
    if stats[0] is None:
        log_to_file(log_filename, f"{datetime.now()} | {symbol} | Недостаточно данных для анализа волатильности {ma_type}\n")
        return None

    current_dist, mean_dist, std_dist, max_dist, min_dist = stats
    current_fast = df[fast_col].iloc[-1]
    current_slow = df[slow_col].iloc[-1]
    previous_fast = df[fast_col].iloc[-2]
    previous_slow = df[slow_col].iloc[-2]

    # signal = "NEUTRAL"
    # if previous_fast < previous_slow and current_fast > current_slow:
    #     signal = "BUY"
    #     signal_text = f"СИГНАЛ ПОКУПКИ: {'Золотой крест' if ma_type == 'SMA' else 'Bullish EMA crossover'}"
    # elif previous_fast > previous_slow and current_fast < current_slow:
    #     signal = "SELL"
    #     signal_text = f"СИГНАЛ ПРОДАЖИ: {'Мертвый крест' if ma_type == 'SMA' else 'Bearish EMA crossover'}"
    # else:
    #     signal_text = f"Пересечения {ma_type} нет - сигнал отсутствует"
    
    crossover_signal = "NEUTRAL"
    if previous_fast < previous_slow and current_fast > current_slow:
        crossover_signal = "BUY"
        crossover_text = f"СИГНАЛ ПОКУПКИ: {'Золотой крест' if ma_type == 'SMA' else 'Bullish EMA crossover'}"
    elif previous_fast > previous_slow and current_fast < current_slow:
        crossover_signal = "SELL" 
        crossover_text = f"СИГНАЛ ПРОДАЖИ: {'Мертвый крест' if ma_type == 'SMA' else 'Bearish EMA crossover'}"
    else:
        crossover_text = f"Пересечения {ma_type} нет"
    # НОВАЯ логика: Анализ силы тренда
    strength_signal = "NEUTRAL"
    strength_text = ""
    
    # Критерий 1: Наклон быстрой MA (положительный/отрицательный)
    ma_slope = current_fast - previous_fast
    
    # Критерий 2: "Уверенная" торговля выше/ниже (на основе расстояния и волатильности)
    confidence_threshold = std_dist * 0.5  # Порог уверенности = 0.5 стандартных отклонений
    
    if current_dist > confidence_threshold and ma_slope > 0:
        strength_signal = "BULLISH"
        strength_text = f" | Уверенный бычий тренд (расстояние: {current_dist:+.2f}%)"
    elif current_dist < -confidence_threshold and ma_slope < 0:
        strength_signal = "BEARISH" 
        strength_text = f" | Уверенный медвежий тренд (расстояние: {current_dist:+.2f}%)"
    else:
        strength_text = " | Тренд неопределенный/консолидация"

    # КОМБИНИРОВАННЫЙ сигнал
    if crossover_signal != "NEUTRAL":
        final_signal = crossover_signal
        final_text = crossover_text + strength_text
    else:
        final_signal = strength_signal
        final_text = f"Сигнал по {ma_type}: {strength_signal}" + strength_text

    # log_str = (
    #     f"{datetime.now()} | {symbol} | {ma_type}\n"  # <--- добавлено название монеты и тип MA
    #     f"{ma_type}{fast_period}: {current_fast:.2f}\n"
    #     f"{ma_type}{slow_period}: {current_slow:.2f}\n"
    #     f"Текущее расстояние между {ma_type}: {current_dist:+.2f}%\n"
    #     f"Исторический диапазон: [{min_dist:+.2f}%, {max_dist:+.2f}%]\n"
    #     f"{signal_text}\n"
    #     f"---\n"
    # )
    # log_to_file(log_filename, log_str)

    # В секции логирования после расчета статистики:
    range_width = max_dist - min_dist
    normalized_position = (current_dist - min_dist) / range_width if range_width > 0 else 0.5

    # Создаем простой текстовый прогресс-бар
    bar_length = 20
    position_index = int(normalized_position * bar_length)
    progress_bar = "[" + "=" * position_index + "|" + "=" * (bar_length - position_index - 1) + "]"

    return {
        'bar': {f"Текущее расстояние: {current_dist:+.2f}% {progress_bar}\n"},
        'signal': {f"Сигнал: {final_text}\n"},
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
    Требуется столбец 'close'.
    Возвращает DataFrame с колонками 'macd', 'macd_signal', 'macd_hist'.
    Логирует последний сигнал.
    """
    ema_fast = df['close'].ewm(span=fast_period, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow_period, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal_period, adjust=False).mean()
    macd_hist = macd - macd_signal

    # Текущие значения
    last_macd = macd.iloc[-1]
    last_signal = macd_signal.iloc[-1]
    last_hist = macd_hist.iloc[-1]
    
    # ПРЕДЫДУЩИЕ значения для анализа тренда
    prev_macd = macd.iloc[-2]
    prev_signal = macd_signal.iloc[-2]
    prev_hist = macd_hist.iloc[-2]

    # УЛУЧШЕННАЯ логика определения сигнала
    signal = "NEUTRAL"
    details = []
    
    # 1. Анализ положения относительно нуля (тренд)
    if last_macd > 0 and last_signal > 0:
        details.append("Бычий тренд (выше нуля)")
    elif last_macd < 0 and last_signal < 0:
        details.append("Медвежий тренд (ниже нуля)")
    else:
        details.append("Переходная зона")
    
    # 2. Анализ пересечения линий (моментum)
    if last_macd > last_signal and prev_macd <= prev_signal:
        signal = "BUY"
        details.append("ПЕРЕСЕЧЕНИЕ СНИЗУ ВВЕРХ")
    elif last_macd < last_signal and prev_macd >= prev_signal:
        signal = "SELL" 
        details.append("ПЕРЕСЕЧЕНИЕ СВЕРХУ ВНИЗ")
    elif last_macd > last_signal:
        signal = "BULLISH"
        details.append("Бычье расположение")
    elif last_macd < last_signal:
        signal = "BEARISH"
        details.append("Медвежье расположение")
    
    # 3. Анализ гистограммы (импульс)
    if last_hist > 0 and last_hist > prev_hist:
        details.append("Импульс усиливается")
    elif last_hist > 0 and last_hist < prev_hist:
        details.append("Импульс ослабевает")
    elif last_hist < 0 and last_hist < prev_hist:
        details.append("Спад усиливается")
    elif last_hist < 0 and last_hist > prev_hist:
        details.append("Спад ослабевает")

    # УЛУЧШЕННОЕ логирование
    log_str = (
        f"{datetime.now()} | {symbol} | MACD АНАЛИЗ\n"
        f"MACD: {last_macd:.6f} | Signal: {last_signal:.6f} | Hist: {last_hist:.6f}\n"
        f"Положение: {'Выше нуля' if last_macd > 0 else 'Ниже нуля'} | "
        f"Гистограмма: {'Положительная' if last_hist > 0 else 'Отрицательная'}\n"
        f"СИГНАЛ: {signal} | Детали: {', '.join(details)}\n"
        f"---\n"
    )
    log_to_file("macd_log.txt", log_str)

    result = pd.DataFrame({
        'macd': macd,
        'macd_signal': macd_signal,
        'macd_hist': macd_hist
    })

    # сохранить сводный сигнал в attrs (без добавления скалярных столбцов разной длины)
    try:
        result.attrs['summary_signal'] = signal
        result.attrs['summary_details'] = ', '.join(details)
    except Exception:
        pass

    return result
    
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

    if volume_ratio is None:
        signal = "Недостаточно данных для анализа объема"
    elif volume_ratio > 2.0:
        direction = "РОСТЕ" if is_bullish_candle else "ПАДЕНИИ"
        signal = f"🚀 ВЫСОКИЙ ОБЪЕМ НА {direction}! Движение подтверждено"
    elif volume_ratio < 0.5:
        signal = "⚠️  НИЗКИЙ ОБЪЕМ! Движение не подтверждено"
    else:
        signal = "Обычный объем, движение нейтрально"

    # Логирование
    log_str = (
        f"{datetime.now()} | {symbol} | VOLUME\n"
        f"Объем: {current_volume:.0f} vs средний {avg_volume:.0f} (x{volume_ratio:.1f})\n"
        f"Сигнал: {signal}\n"
        f"---\n"
    )
    log_to_file("volume_analysis_log.txt", log_str)

    return {
        "symbol": symbol,
        "current_volume": current_volume,
        "avg_volume": avg_volume,
        "volume_ratio": volume_ratio,
        "signal": signal,
        "log": log_str
    }            
    
def full_multi_timeframe_analysis(
    df_dict,
    fast_period,
    slow_period,
    lookback_periods,
    bb_period=20,
    bb_num_std=2,
    symbol="UNKNOWN"
):
    """
    Анализирует все сигналы по всем таймфреймам и формирует итоговую рекомендацию.
    """
    results = {}
    summary_signals = []
    volume_signals = []
    all_logs = []

    for tf, df in df_dict.items():
        # Анализ по каждому таймфрейму
        sma_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [{tf}]", ma_type="SMA")
        ema_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [{tf}]", ma_type="EMA")
        bb_sma_df = calculate_bollinger_bands(df.copy(), period=bb_period, num_std=bb_num_std, ma_type="SMA", symbol=f"{symbol} [{tf}]")
        bb_ema_df = calculate_bollinger_bands(df.copy(), period=bb_period, num_std=bb_num_std, ma_type="EMA", symbol=f"{symbol} [{tf}]")
        macd_df = calculate_macd(df.copy(), symbol=f"{symbol} [{tf}]")
        volume_res = analyze_volume(df, symbol=f"{symbol} [{tf}]")

        bb_sma_signal = bb_sma_df['bb_signal'].iloc[-1] if not bb_sma_df.empty else None
        bb_ema_signal = bb_ema_df['bb_signal'].iloc[-1] if not bb_ema_df.empty else None
        last_macd = macd_df['macd'].iloc[-1] if not macd_df.empty else None
        last_signal = macd_df['macd_signal'].iloc[-1] if not macd_df.empty else None
        if last_macd is not None and last_signal is not None:
            if last_macd > last_signal:
                macd_signal = "BUY"
            elif last_macd < last_signal:
                macd_signal = "SELL"
            else:
                macd_signal = "NEUTRAL"
        else:
            macd_signal = None

        # Собираем сигналы
        signals = [
            sma_result['signal'] if sma_result else None,
            ema_result['signal'] if ema_result else None,
            bb_sma_signal,
            bb_ema_signal,
            macd_signal
        ]
        summary_signals += [s for s in signals if s in ("BUY", "SELL")]
        if volume_res and volume_res.get("signal"):
            volume_signals.append(volume_res["signal"])

        # Лог по таймфрейму
        log_str = (
            f"{datetime.now()} | {symbol} [{tf}] | FULL ANALYSIS\n"
            f"SMA сигнал: {signals[0]}\n"
            f"{sma_result['current_and_historical_distance'] if sma_result else ''}"
            f"EMA сигнал: {signals[1]}\n"
            f"{ema_result['current_and_historical_distance'] if ema_result else ''}"
            f"Bollinger Bands SMA сигнал: {signals[2]}\n"
            f"Bollinger Bands EMA сигнал: {signals[3]}\n"
            f"MACD сигнал: {signals[4]}\n"
            f"Объем: {volume_res.get('current_volume') if volume_res else 'n/a'} vs средний {volume_res.get('avg_volume') if volume_res else 'n/a'}\n"
            f"Сигнал по объему: {volume_res.get('signal') if volume_res else 'n/a'}\n"
            f"---\n"
        )
        all_logs.append(log_str)

        results[tf] = {
            "sma_signal": signals[0],
            "ema_signal": signals[1],
            "bb_sma_signal": signals[2],
            "bb_ema_signal": signals[3],
            "macd_signal": signals[4],
            "volume_signal": volume_res.get("signal") if volume_res else None,
            "sma_stats": sma_result,
            "ema_stats": ema_result,
            "bb_sma_stats": bb_sma_df.iloc[-1].to_dict() if not bb_sma_df.empty else None,
            "bb_ema_stats": bb_ema_df.iloc[-1].to_dict() if not bb_ema_df.empty else None,
            "macd_stats": macd_df.iloc[-1].to_dict() if not macd_df.empty else None,
            "volume_stats": volume_res
        }

    # Итоговая мульти-таймфрейм рекомендация
    buy_count = summary_signals.count("BUY")
    sell_count = summary_signals.count("SELL")
    total = buy_count + sell_count

    # Итоговый лог
    final_log = "\n".join(all_logs)
    log_to_file("multi_timeframe_analysis_log.txt", final_log)

    return {
        "results": results,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "total_signals": total,
        "volume_signals": volume_signals
    }

