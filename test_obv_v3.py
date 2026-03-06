from analyzes.obv_analyzer_v3 import OBVAnalyzerV3
from bybit_client import bybit_client


def run_obv_v3_test(symbol="BTCUSDT", interval="60"):
    analyzer = OBVAnalyzerV3()

    df = bybit_client.get_klines(symbol, interval=interval)
    if df is None or df.empty:
        print(f"Нет данных для {symbol} [{interval}]")
        return

    report = analyzer.analyze_obv_output(df, symbol=symbol, timeframe="1H")
    print(report)

    latest = analyzer.get_latest_obv_state(symbol=symbol, timeframe="1H", as_dict=True)
    print("\n=== LATEST OBV STATE (DICT) ===")
    print(latest)


if __name__ == "__main__":
    run_obv_v3_test(symbol="BTCUSDT", interval="60")
