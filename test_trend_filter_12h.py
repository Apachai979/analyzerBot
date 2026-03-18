import pandas as pd

from bybit_client import bybit_client
from analyzes.trend_filter_12h_v2 import trend_filter_12h, TrendFilter12hConfig


def prepare_ohlcv_for_filter(
    raw_df: pd.DataFrame,
    interval_minutes: int,
    drop_incomplete_last_candle: bool = True,
) -> pd.DataFrame:
    df = raw_df.copy()

    # Приведение типов
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Индекс + базовая очистка
    df = df.set_index("timestamp")
    df = df[["open", "high", "low", "close", "volume"]]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.dropna()

    if df.empty:
        return df

    # Удаляем текущую незакрытую свечу
    if drop_incomplete_last_candle:
        now_utc = pd.Timestamp.now(tz="UTC")

        interval_delta = pd.Timedelta(minutes=interval_minutes)
        interval_ns = interval_delta.value

        # start текущего интервала
        current_bucket_start = pd.Timestamp(
            (now_utc.value // interval_ns) * interval_ns,
            tz="UTC",
        )

        # Если последняя свеча началась в текущем интервале,
        # значит она еще формируется и ее нужно убрать
        if df.index[-1] >= current_bucket_start:
            df = df.iloc[:-1]

    return df


def run(symbol: str = "BTCUSDT", interval: str = "720", limit: int = 400) -> None:
    # ВАЖНО: в самом bybit_client.get_klines(...) проверь, что category="spot"
    raw = bybit_client.get_klines(symbol=symbol, interval=interval, limit=limit)
    if raw is None or raw.empty:
        print(f"Нет данных: {symbol} [{interval}]")
        return

    interval_minutes = int(interval)
    df_12h = prepare_ohlcv_for_filter(
        raw_df=raw,
        interval_minutes=interval_minutes,
        drop_incomplete_last_candle=True,
    )

    if df_12h.empty:
        print(f"После очистки не осталось данных: {symbol} [{interval}]")
        return

    result = trend_filter_12h(
        df_12h,
        config=TrendFilter12hConfig(
            min_required_rows=260,
            min_soft_conditions_passed=2,
        ),
    )

    print(f"\n=== TREND FILTER 12H V2: {symbol} ===")
    print(f"bars={len(df_12h)}")
    print(f"last_closed_candle={df_12h.index[-1]}")
    print(f"passed={result.passed}")
    print(f"hard_passed={result.hard_passed}")
    print(f"soft_score={result.soft_score}/{result.soft_score_max}")
    print(f"reason={result.reason}")
    print("\n--- details ---")
    print(result.details)


if __name__ == "__main__":
    run(symbol="BTCUSDT", interval="720", limit=400)