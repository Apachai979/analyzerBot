from datetime import datetime
import numpy as np
import pandas as pd


def calculate_atr(df, period=14):
    df = df.copy()
    if len(df) < period:
        return "Недостаточно данных для расчета ATR\n", None

    df['prev_close'] = df['close'].shift(1)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = (df['high'] - df['prev_close']).abs()
    df['tr3'] = (df['low'] - df['prev_close']).abs()
    df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['ATR'] = df['true_range'].rolling(window=period).mean()

    if df['ATR'].dropna().empty:
        return "Недостаточно данных для расчета ATR\n", None

    last_atr = df['ATR'].iloc[-1]
    atr_pct = (df['ATR'] / df['close'].replace(0, np.nan)) * 100
    low_threshold = np.percentile(atr_pct.dropna(), 25)
    high_threshold = np.percentile(atr_pct.dropna(), 75)
    current_atr_pct = atr_pct.iloc[-1]

    if current_atr_pct < low_threshold:
        volatility = "НИЗКАЯ"
    elif current_atr_pct > high_threshold:
        volatility = "ВЫСОКАЯ"
    else:
        volatility = "СРЕДНЯЯ"

    log_str = (
        f"=== ATR ANALYSIS ===\n"
        f"Период: {period}\n"
        f"ATR: {last_atr:.4f}\n"
        f"Текущий ATR%: {current_atr_pct:.2f}%\n"
        f"Порог низкой: {low_threshold:.2f}% | Порог высокой: {high_threshold:.2f}%\n"
        f"Волатильность: {volatility}\n"
        f"---\n"
    )
    # Возвращаем log и DataFrame с ATR и волатильностью
    result = pd.DataFrame({
        'ATR': df['ATR'],
        'ATR_PCT': atr_pct,
        'volatility': [volatility]*len(df)
    })
    return log_str, result

def calculate_rsi(df, period=14):
    df = df.copy()
    if len(df) < period:
        return "Недостаточно данных для расчета RSI\n", None

    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    if rsi.dropna().empty:
        return "Недостаточно данных для расчета RSI\n", None

    last_rsi = rsi.iloc[-1]
    if last_rsi >= 70:
        rsi_state = "ПЕРЕКУПЛЕННОСТЬ"
    elif last_rsi <= 30:
        rsi_state = "ПЕРЕПРОДАННОСТЬ"
    else:
        rsi_state = "НЕЙТРАЛЬНО"

    log_str = (
        f"=== RSI ANALYSIS ===\n"
        f"Период: {period}\n"
        f"RSI: {last_rsi:.2f}\n"
        f"Состояние: {rsi_state}\n"
        f"---\n"
    )
    # Возвращаем log и Series с RSI
    return log_str, rsi

def calculate_stochastic(df, k_period=14, d_period=3):
    df = df.copy()
    if len(df) < k_period:
        return "Недостаточно данных для расчета Stochastic\n", None

    low_min = df['low'].rolling(window=k_period).min()
    high_max = df['high'].rolling(window=k_period).max()
    stoch_k = 100 * (df['close'] - low_min) / (high_max - low_min)
    stoch_d = stoch_k.rolling(window=d_period).mean()

    if stoch_k.dropna().empty or stoch_d.dropna().empty:
        return "Недостаточно данных для расчета Stochastic\n", None

    last_k = stoch_k.iloc[-1]
    last_d = stoch_d.iloc[-1]

    if last_k >= 80 and last_d >= 80:
        stoch_state = "ПЕРЕКУПЛЕННОСТЬ"
    elif last_k <= 20 and last_d <= 20:
        stoch_state = "ПЕРЕПРОДАННОСТЬ"
    else:
        stoch_state = "НЕЙТРАЛЬНО"

    log_str = (
        f"=== STOCHASTIC ANALYSIS ===\n"
        f"k_period: {k_period}, d_period: {d_period}\n"
        f"Stoch %K: {last_k:.2f}\n"
        f"Stoch %D: {last_d:.2f}\n"
        f"Состояние: {stoch_state}\n"
        f"---\n"
    )
    # Возвращаем log и DataFrame с %K и %D
    return log_str, pd.DataFrame({'stoch_k': stoch_k, 'stoch_d': stoch_d})

def full_atr_rsi_sto_multi_analysis(df_dict, symbol="UNKNOWN", atr_period=14, rsi_period=14, k_period=14, d_period=3):
    """
    df_dict: {'1h': df_1h, '4h': df_4h, ...}
    Анализирует ATR, RSI, Stochastic для каждого таймфрейма.
    """
    all_results = {}
    all_logs = []
    for tf, df in df_dict.items():
        header = f"{datetime.now()} | {symbol} [{tf}] | ATR/RSI/Stochastic FULL ANALYSIS\n"
        atr_log, atr_res = calculate_atr(df, atr_period)
        rsi_log, rsi_res = calculate_rsi(df, rsi_period)
        stoch_log, stoch_res = calculate_stochastic(df, k_period, d_period)
        log_str = header + atr_log + rsi_log + stoch_log
        all_logs.append(log_str)
        all_results[tf] = {
            "atr": atr_res,
            "rsi": rsi_res,
            "stochastic": stoch_res
        }
    return all_results