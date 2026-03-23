from __future__ import annotations

import pandas as pd


def format_price(price, reference_price):
    if price is None or reference_price is None:
        return str(price)

    ref_str = f"{reference_price:.15f}".rstrip('0').rstrip('.')
    if '.' in ref_str:
        decimal_places = len(ref_str.split('.')[1])
    else:
        decimal_places = 0

    formatted = f"{price:.{decimal_places}f}".rstrip('0').rstrip('.')
    return formatted


def prepare_ohlcv_for_filter(raw_df, interval_minutes, drop_incomplete_last_candle=True):
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    df = raw_df.copy()
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.set_index("timestamp")
    df = df[["open", "high", "low", "close", "volume"]]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.dropna()

    if df.empty:
        return df

    if drop_incomplete_last_candle:
        now_utc = pd.Timestamp.now(tz="UTC")
        interval_delta = pd.Timedelta(minutes=interval_minutes)
        interval_ns = interval_delta.value
        current_bucket_start = pd.Timestamp(
            (now_utc.value // interval_ns) * interval_ns,
            tz="UTC",
        )
        if df.index[-1] >= current_bucket_start:
            df = df.iloc[:-1]

    return df


def derive_filter_action(passed, hard_passed, soft_score, required_score):
    if passed:
        return "GO"
    if hard_passed and soft_score >= max(1, required_score - 1):
        return "ATTENTION"
    return "STOP"


def format_bias_summary(label, result):
    required_score = result.details.get("soft_score_required", result.soft_score_max)
    status = "GO" if result.passed else ("ATTENTION" if result.hard_passed else "STOP")
    return (
        f"{label} BIAS: {status}\n"
        f"Hard: {'OK' if result.hard_passed else 'FAIL'} | Soft: {result.soft_score}/{result.soft_score_max} (need {required_score})\n"
        f"Reason: {result.reason}"
    )


def format_setup_summary(label, result):
    required_score = result.details.get("soft_score_required", result.soft_score_max)
    obv = result.details.get("obv", {})
    obv_score = sum(
        int(obv.get(key, False))
        for key in ["obv_bullish_state", "obv_strength_supportive", "obv_bullish_divergence"]
    )
    soft = result.details.get("soft_conditions", {})
    return (
        f"{label} SETUP: {result.setup_state}\n"
        f"Hard: {'OK' if result.hard_passed else 'FAIL'} | Soft: {result.soft_score}/{result.soft_score_max} (need {required_score})\n"
        f"Pullback: {'YES' if soft.get('touched_working_zone') else 'NO'} | Reclaim EMA20: {'YES' if soft.get('reclaimed_ema20') else 'NO'} | OBV: {obv_score}/3\n"
        f"Reason: {result.reason}"
    )


def format_trigger_summary(label, result):
    required_score = result.details.get("soft_score_required", result.soft_score_max)
    lines = [
        f"{label} TRIGGER: {result.action}",
        f"State: {result.trigger_state}",
        f"Hard: {'OK' if result.hard_passed else 'FAIL'} | Soft: {result.soft_score}/{result.soft_score_max} (need {required_score})",
    ]
    if result.entry_price is not None:
        lines.append(
            f"Entry: {result.entry_price} | SL: {result.stop_loss} | TP: {result.take_profit} | RR: {result.reward_risk:.2f}"
        )
    lines.append(f"Reason: {result.reason}")
    return "\n".join(lines)