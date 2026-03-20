import pandas as pd

from bybit_client_v2 import bybit_client
from analyzes.entry_trigger_1h import EntryTrigger1hConfig, entry_trigger_1h
from analyzes.setup_filter_4h import SetupFilter4hConfig, setup_filter_4h
from analyzes.trend_filter_12h_v2 import TrendFilter12hConfig, trend_filter_12h


def prepare_ohlcv_for_filter(
    raw_df: pd.DataFrame,
    interval_minutes: int,
    drop_incomplete_last_candle: bool = True,
) -> pd.DataFrame:
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


def run(symbol: str = "BTCUSDT", limit_12h: int = 400, limit_4h: int = 400, limit_1h: int = 400) -> None:
    raw_12h = bybit_client.get_klines(symbol=symbol, interval="720", limit=limit_12h)
    raw_4h = bybit_client.get_klines(symbol=symbol, interval="240", limit=limit_4h)
    raw_1h = bybit_client.get_klines(symbol=symbol, interval="60", limit=limit_1h)

    if raw_12h is None or raw_12h.empty:
        print(f"Нет 12h данных: {symbol}")
        return
    if raw_4h is None or raw_4h.empty:
        print(f"Нет 4h данных: {symbol}")
        return
    if raw_1h is None or raw_1h.empty:
        print(f"Нет 1h данных: {symbol}")
        return

    df_12h = prepare_ohlcv_for_filter(raw_12h, interval_minutes=720, drop_incomplete_last_candle=True)
    df_4h = prepare_ohlcv_for_filter(raw_4h, interval_minutes=240, drop_incomplete_last_candle=True)
    df_1h = prepare_ohlcv_for_filter(raw_1h, interval_minutes=60, drop_incomplete_last_candle=True)

    trend_result = trend_filter_12h(
        df_12h,
        config=TrendFilter12hConfig(min_required_rows=260, min_soft_conditions_passed=2),
    )
    setup_result = setup_filter_4h(
        df_4h,
        trend_bias_passed=trend_result.passed,
        trend_bias_reason=trend_result.reason,
        config=SetupFilter4hConfig(min_required_rows=220, min_soft_conditions_passed=6),
    )
    trigger_result = entry_trigger_1h(
        df_1h,
        setup_result=setup_result,
        config=EntryTrigger1hConfig(min_required_rows=180, min_soft_conditions_passed=5),
    )

    print(f"\n=== 12H TREND FILTER: {symbol} ===")
    print(f"passed={trend_result.passed}")
    print(f"reason={trend_result.reason}")

    print(f"\n=== 4H SETUP FILTER: {symbol} ===")
    print(f"passed={setup_result.passed}")
    print(f"setup_state={setup_result.setup_state}")
    print(f"reason={setup_result.reason}")

    print(f"\n=== 1H ENTRY TRIGGER: {symbol} ===")
    print(f"bars={len(df_1h)}")
    print(f"last_closed_candle={df_1h.index[-1]}")
    print(f"passed={trigger_result.passed}")
    print(f"action={trigger_result.action}")
    print(f"trigger_state={trigger_result.trigger_state}")
    print(f"soft_score={trigger_result.soft_score}/{trigger_result.soft_score_max}")
    print(f"reason={trigger_result.reason}")
    print(f"entry={trigger_result.entry_price}")
    print(f"stop={trigger_result.stop_loss}")
    print(f"take={trigger_result.take_profit}")
    print(f"rr={trigger_result.reward_risk}")
    print("\n--- details ---")
    print(trigger_result.details)


if __name__ == "__main__":
    run(symbol="BTCUSDT")