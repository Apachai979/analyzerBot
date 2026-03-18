import pandas as pd

def get_klines(
    self,
    symbol: str,
    interval: str = INTERVAL,
    limit: int = LIMIT,
    category: str = CATEGORY,
) -> pd.DataFrame | None:
    """Получаем исторические свечи Bybit V5 для конкретного инструмента."""
    try:
        if not self.session:
            self._initialize_session()
            if not self.session:
                return None

        if category != "spot":
            raise ValueError(f"Expected category='spot', got {category!r}")

        self._wait_for_rate_limit()

        response = self.session.get_kline(
            category=category,
            symbol=symbol,
            interval=interval,
            limit=limit,
        )

        if response.get("retCode") != 0:
            print(f"❌ Ошибка API при получении свечей {symbol}: {response.get('retMsg')}")
            return None

        result = response.get("result", {})
        klines = result.get("list", [])

        if not klines:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"]
            )

        df = pd.DataFrame(
            klines,
            columns=["timestamp", "open", "high", "low", "close", "volume", "turnover"],
        )

        numeric_columns = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]
        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        df = df.sort_values("timestamp")
        df = df.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

        return df

    except Exception as e:
        print(f"❌ Ошибка при получении данных {symbol}: {e}")
        return None