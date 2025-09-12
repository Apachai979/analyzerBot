from datetime import datetime
import numpy as np
import pandas as pd
import os

LOGS_DIR = "logs"
LOG_FILE = "atr_rsi_sto_full_log.txt"

def log_to_file(text):
    os.makedirs(LOGS_DIR, exist_ok=True)
    full_path = os.path.join(LOGS_DIR, LOG_FILE)
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(text)

def calculate_atr(df, period=14):
    df = df.copy()
    df['prev_close'] = df['close'].shift(1)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = (df['high'] - df['prev_close']).abs()
    df['tr3'] = (df['low'] - df['prev_close']).abs()
    df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['ATR'] = df['true_range'].rolling(window=period).mean()
    last_atr = df['ATR'].iloc[-1]

    atr_pct = (df['ATR'] / df['close']) * 100
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
        f"=== ATR FULL ANALYSIS ===\n"
        f"Период: {period}\n"
        f"ATR: {last_atr:.4f}\n"
        f"Текущий ATR%: {current_atr_pct:.2f}%\n"
        f"Порог низкой: {low_threshold:.2f}% | Порог высокой: {high_threshold:.2f}%\n"
        f"Волатильность: {volatility}\n"
        f"---\n"
    )
    return log_str, {
        "current_atr": last_atr,
        "current_atr_pct": current_atr_pct,
        "low_threshold": low_threshold,
        "high_threshold": high_threshold,
        "volatility": volatility,
        "atr_series": df['ATR']
    }

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
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
    return log_str, rsi

def calculate_stochastic(df, k_period=14, d_period=3):
    low_min = df['low'].rolling(window=k_period).min()
    high_max = df['high'].rolling(window=k_period).max()
    stoch_k = 100 * (df['close'] - low_min) / (high_max - low_min)
    stoch_d = stoch_k.rolling(window=d_period).mean()
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
    log_to_file("\n".join(all_logs))
    return all_results