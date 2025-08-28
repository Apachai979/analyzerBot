import requests
import pandas as pd
from datetime import datetime, timedelta
from config import SYMBOLS

COINMETRICS_COMMUNITY_API = "https://community-api.coinmetrics.io/v4"
# Добавьте сюда крупные монеты для сравнения
MAJOR_ASSETS = ["btc", "eth", "bnb", "sol"]

def get_asset_prices(asset, start, end, frequency="1d"):
    url = f"{COINMETRICS_COMMUNITY_API}/timeseries/asset-metrics"
    params = {
        "assets": asset.lower(),
        "metrics": "PriceUSD",
        "frequency": frequency,
        "start_time": start,
        "end_time": end,
    }
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if "data" not in data or not data["data"]:
            print(f"Нет данных для {asset.upper()}")
            return None
        df = pd.DataFrame(data["data"])
        df["time"] = pd.to_datetime(df["time"])
        df.set_index("time", inplace=True)
        df = df.rename(columns={"PriceUSD": asset.upper()})
        df[asset.upper()] = pd.to_numeric(df[asset.upper()], errors="coerce")
        return df[[asset.upper()]]
    except requests.HTTPError as e:
        print(f"Ошибка для {asset.upper()}: {e}")
        return None

def get_correlation_matrix(symbols, major_assets=None, days=90):
    if major_assets is None:
        major_assets = []
    all_assets = set([s.replace("USDT", "").lower() for s in symbols] + major_assets)
    end = datetime.now().date()
    start = end - timedelta(days=days)
    dfs = []
    for asset in all_assets:
        df = get_asset_prices(asset, start.isoformat(), end.isoformat())
        if df is not None:
            dfs.append(df)
    if not dfs:
        print("Нет данных для расчёта корреляции.")
        return None
    df_all = pd.concat(dfs, axis=1)
    corr = df_all.corr(method="pearson")
    print("Корреляционная матрица (за последние %d дней):" % days)
    print(corr)
    return corr

if __name__ == "__main__":
    # Пример использования
    get_correlation_matrix(SYMBOLS, MAJOR_ASSETS, days=90)