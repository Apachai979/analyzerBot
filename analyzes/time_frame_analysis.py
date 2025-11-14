from analyzes.multi_timeframe_ma_analysis import (
    analyze_ma_signals,
    calculate_macd,
    analyze_volume,
    calculate_bollinger_bands,
    log_to_file,
    calculate_bollinger_bands_1D
)
from analyzes.atr_rsi_stochastic import calculate_rsi, calculate_atr, calculate_stochastic

def adjust_periods_for_history(df, fast_period, slow_period, lookback_periods, min_required=6):
    """
    Если данных мало, уменьшает периоды индикаторов до максимально возможных.
    Если данных достаточно — возвращает исходные периоды.
    """
    available = len(df)
    if df is None or available < min_required:
        return None
    min_period = max(fast_period, slow_period, lookback_periods)
    if available >= min_period + 2:
        # Данных достаточно для стандартных периодов
        return fast_period, slow_period, lookback_periods
    # Если данных мало — уменьшаем периоды
    fast_period = max(2, int(available * 0.3))
    slow_period = max(3, int(available * 0.95))
    lookback_periods = max(2, available // 2)
    return fast_period, slow_period, lookback_periods

def analyze_1d_ma_macd_volume(df, symbol="UNKNOWN"):
    """
    Анализирует дневные сигналы SMA/EMA (50, 200), MACD, Volume и Bollinger Bands (SMA).
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    
    fast_period = 50
    slow_period = 200
    lookback_periods = 100

    adjusted = adjust_periods_for_history(df, fast_period, slow_period, lookback_periods)
    if adjusted is None:
        print(f"{datetime.now()} | {symbol} | Слишком мало данных для анализа {ma_type}\n")
        return None
    fast_period, slow_period, lookback_periods = adjusted
    if slow_period < 30:
        print(f"{datetime.now()} | {symbol} | Слишком мало данных для анализа {ma_type}\n")
        return None
    # SMA/EMA анализ
    sma_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [1D]", ma_type="SMA")
    ema_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [1D]", ma_type="EMA")

    # MACD анализ
    macd_df = calculate_macd(df.copy(), fast_period=12, slow_period=26, signal_period=9, symbol=f"{symbol} [1D]") 
    
    # Volume анализ
    volume_res = analyze_volume(df.copy(), volume_ma_period=20, symbol=f"{symbol} [1D]")

    # Bollinger Bands анализ на SMA
    bb_sma_df = calculate_bollinger_bands_1D(df.copy(), period=20, num_std=2, ma_type="EMA", symbol=f"{symbol} [1D]", trend_direction=f"{sma_result['signal']}")
    bb_sma_signal = bb_sma_df['bb_signal'].iloc[-1] if not bb_sma_df.empty else None

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 1D MA/MACD/Volume/BB Analysis ===\n"
        f"SMA(50/200) сигнал: {f'{sma_result.get('signal','n/a')} {sma_result.get('bar','n/a')}' if isinstance(sma_result, dict) else 'n/a'}"
        f"EMA(50/200) сигнал: {f'{ema_result.get('signal','n/a')} {ema_result.get('bar','n/a')}' if isinstance(ema_result, dict) else 'n/a'}"
        f"MACD сигнал: {macd_df.attrs.get('summary_signal')}, details: {macd_df.attrs.get('summary_details')}\n"
        f"Bollinger Bands SMA сигнал: {bb_sma_signal}\n"
        f"Объем: {volume_res.get('current_volume', 'n/a')} vs средний {volume_res.get('avg_volume', 'n/a')}\n"
        f"Сигнал по объему: {volume_res.get('signal', 'n/a')}\n"
        f"---\n"
    )

    # Логирование
    log_to_file("ma_macd_volume_1d_log.txt", summary)

    return {
        "sma_result": sma_result,
        "ema_result": ema_result,
        # "macd_signal": macd_signal,
        "volume_result": volume_res,
        "bb_sma_signal": bb_sma_signal,
        "summary": summary
    }

def analyze_12h_ema_macd_rsi_atr(df, symbol="UNKNOWN"):
    """
    Анализирует 12h сигналы EMA(21, 50), MACD, RSI, ATR.
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    fast_period = 21
    slow_period = 50
    lookback_periods = 60

    # EMA анализ
    ema_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [12H]", ma_type="EMA")

    # MACD анализ
    macd_df = calculate_macd(df.copy(), fast_period=12, slow_period=26, signal_period=9, symbol=f"{symbol} [12H]")
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

    # RSI анализ

    rsi_log, rsi_series = calculate_rsi(df, period=14)
    last_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None
    if last_rsi is not None:
        if last_rsi >= 70:
            rsi_state = "ПЕРЕКУПЛЕННОСТЬ"
        elif last_rsi <= 30:
            rsi_state = "ПЕРЕПРОДАННОСТЬ"
        else:
            rsi_state = "НЕЙТРАЛЬНО"
    else:
        rsi_state = "n/a"

    # ATR анализ
    atr_log, atr_res = calculate_atr(df, period=14)
    atr_value = atr_res["current_atr"] if atr_res else None
    atr_pct = atr_res["current_atr_pct"] if atr_res else None
    volatility = atr_res["volatility"] if atr_res else None

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 12H EMA/MACD/RSI/ATR Analysis ===\n"
        f"EMA(21/50) сигнал: {ema_result['signal'] if ema_result else 'n/a'}\n"
        f"MACD сигнал: {macd_signal}\n"
        f"RSI: {last_rsi:.2f} ({rsi_state})\n"
        f"ATR: {atr_value:.4f}, %: {atr_pct:.2f}, Волатильность: {volatility}\n"
        f"---\n"
    )

    # Логирование
    log_to_file("ema_macd_rsi_atr_12h_log.txt", summary)

    return {
        "ema_result": ema_result,
        "macd_signal": macd_signal,
        "rsi": last_rsi,
        "rsi_state": rsi_state,
        "atr": atr_value,
        "atr_pct": atr_pct,
        "volatility": volatility,
        "summary": summary
    }

def analyze_4h_bb_stoch_ma_volume(df, symbol="UNKNOWN"):
    """
    Анализирует 4h сигналы: Bollinger Bands, Stochastic (14,3,3), RSI (14), Volume, SMA/EMA (20).
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    ma_period = 20
    bb_period = 20
    bb_num_std = 2
    stoch_k_period = 14
    stoch_d_period = 3
    stoch_smooth = 3
    rsi_period = 14
    volume_ma_period = 20

    # Bollinger Bands (SMA)
    bb_sma_df = calculate_bollinger_bands(df.copy(), period=bb_period, num_std=bb_num_std, ma_type="SMA", symbol=f"{symbol} [4H]")
    bb_sma_signal = bb_sma_df['bb_signal'].iloc[-1] if not bb_sma_df.empty else None

    # Stochastic (14,3,3)
    stoch_df = calculate_stochastic(df.copy(), k_period=stoch_k_period, d_period=stoch_d_period)
    stoch_k = stoch_df['stoch_k'].iloc[-1] if not stoch_df.empty else None
    stoch_d = stoch_df['stoch_d'].iloc[-1] if not stoch_df.empty else None

    # RSI (14)
    rsi_log, rsi_series = calculate_rsi(df, period=rsi_period)
    last_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None

    # Volume
    volume_res = analyze_volume(df, volume_ma_period=volume_ma_period, symbol=f"{symbol} [4H]")

    # SMA/EMA (20)
    sma_result = analyze_ma_signals(df.copy(), ma_period, ma_period, 40, symbol=f"{symbol} [4H]", ma_type="SMA")
    ema_result = analyze_ma_signals(df.copy(), ma_period, ma_period, 40, symbol=f"{symbol} [4H]", ma_type="EMA")

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 4H BB/Stochastic/MA/Volume Analysis ===\n"
        f"Bollinger Bands SMA сигнал: {bb_sma_signal}\n"
        f"Stochastic %K: {stoch_k:.2f if stoch_k is not None else 'n/a'}, %D: {stoch_d:.2f if stoch_d is not None else 'n/a'}\n"
        f"RSI: {last_rsi:.2f if last_rsi is not None else 'n/a'}\n"
        f"SMA(20) сигнал: {sma_result['signal'] if sma_result else 'n/a'}\n"
        f"EMA(20) сигнал: {ema_result['signal'] if ema_result else 'n/a'}\n"
        f"Объем: {volume_res.get('current_volume', 'n/a')} vs средний {volume_res.get('avg_volume', 'n/a')}\n"
        f"Сигнал по объему: {volume_res.get('signal', 'n/a')}\n"
        f"---\n"
    )

    # Логирование
    log_to_file("bb_stoch_ma_volume_4h_log.txt", summary)

    return {
        "bb_sma_signal": bb_sma_signal,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "rsi": last_rsi,
        "sma_result": sma_result,
        "ema_result": ema_result,
        "volume_result": volume_res,
        "summary": summary
    }   
    
def analyze_1h_ema_macd_atr_rsi(df, symbol="UNKNOWN"):
    """
    Анализирует 1h сигналы: EMA(9, 20), MACD (fast), ATR, RSI.
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    fast_period = 9
    slow_period = 20
    lookback_periods = 40

    # EMA анализ
    ema_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [1H]", ma_type="EMA")

    # MACD анализ (быстрые настройки)
    macd_df = calculate_macd(df.copy(), fast_period=6, slow_period=13, signal_period=4, symbol=f"{symbol} [1H]")
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

    # ATR анализ
    from analyzes.atr_rsi_stochastic import calculate_atr, calculate_rsi
    atr_log, atr_res = calculate_atr(df, period=14)
    atr_value = atr_res["current_atr"] if atr_res else None
    atr_pct = atr_res["current_atr_pct"] if atr_res else None
    volatility = atr_res["volatility"] if atr_res else None

    # RSI анализ
    rsi_log, rsi_series = calculate_rsi(df, period=14)
    last_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None
    if last_rsi is not None:
        if last_rsi >= 70:
            rsi_state = "ПЕРЕКУПЛЕННОСТЬ"
        elif last_rsi <= 30:
            rsi_state = "ПЕРЕПРОДАННОСТЬ"
        else:
            rsi_state = "НЕЙТРАЛЬНО"
    else:
        rsi_state = "n/a"

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 1H EMA/MACD/ATR/RSI Analysis ===\n"
        f"EMA(9/20) сигнал: {ema_result['signal'] if ema_result else 'n/a'}\n"
        f"MACD (fast) сигнал: {macd_signal}\n"
        f"ATR: {atr_value:.4f if atr_value is not None else 'n/a'}, %: {atr_pct:.2f if atr_pct is not None else 'n/a'}, Волатильность: {volatility}\n"
        f"RSI: {last_rsi:.2f if last_rsi is not None else 'n/a'} ({rsi_state})\n"
        f"---\n"
    )

    # Логирование
    log_to_file("ema_macd_atr_rsi_1h_log.txt", summary)

    return {
        "ema_result": ema_result,
        "macd_signal": macd_signal,
        "atr": atr_value,
        "atr_pct": atr_pct,
        "volatility": volatility,
        "rsi": last_rsi,
        "rsi_state": rsi_state,
        "summary": summary
    }
    
def analyze_15m_stoch_ema_volume(df, symbol="UNKNOWN"):
    """
    Анализирует 15m сигналы: Stochastic (5,3,3), EMA(9), Volume.
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    stoch_k_period = 5
    stoch_d_period = 3
    stoch_smooth = 3
    ema_period = 9
    volume_ma_period = 20

    # Stochastic (5,3,3)
    from analyzes.atr_rsi_stochastic import calculate_stochastic
    stoch_log, data = calculate_stochastic(df.copy(), k_period=stoch_k_period, d_period=stoch_d_period)
    stoch_k = data['stoch_k'].iloc[-1] if not data.empty else None
    stoch_d = data['stoch_d'].iloc[-1] if not data.empty else None

    # EMA(9)
    from analyzes.multi_timeframe_ma_analysis import calculate_ema
    ema_series = calculate_ema(df['close'], ema_period)
    last_ema = ema_series.iloc[-1] if not ema_series.empty else None
    last_price = df['close'].iloc[-1] if not df.empty else None
    if last_ema is not None and last_price is not None:
        if last_price > last_ema:
            ema_signal = "BUY"
        elif last_price < last_ema:
            ema_signal = "SELL"
        else:
            ema_signal = "NEUTRAL"
    else:
        ema_signal = "n/a"

    # Volume
    from analyzes.multi_timeframe_ma_analysis import analyze_volume
    volume_res = analyze_volume(df, volume_ma_period=volume_ma_period, symbol=f"{symbol} [15m]")

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 15m Stochastic/EMA/Volume Analysis ===\n"
        f"Stochastic %K: {stoch_k:.2f if stoch_k is not None else 'n/a'}, %D: {stoch_d:.2f if stoch_d is not None else 'n/a'}\n"
        f"EMA(9) сигнал: {ema_signal}\n"
        f"Объем: {volume_res.get('current_volume', 'n/a')} vs средний {volume_res.get('avg_volume', 'n/a')}\n"
        f"Сигнал по объему: {volume_res.get('signal', 'n/a')}\n"
        f"---\n"
    )

    # Логирование
    log_to_file("stoch_ema_volume_15m_log.txt", summary)

    return {
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "ema_signal": ema_signal,
        "volume_result": volume_res,
        "summary": summary
    }