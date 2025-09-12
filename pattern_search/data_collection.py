import datetime
from bybit_client import bybit_client
from coinmarketcap_client import get_coinmarketcap_data, get_fear_greed_index
from defillama_client import DefiLlamaClient

class PatternCollector:
    def __init__(self, symbols):
        self.symbols = symbols
        self.defillama = DefiLlamaClient()
        self.period_days = 11  # полторы недели

    def collect(self):
        end_time = datetime.datetime.utcnow()
        start_time = end_time - datetime.timedelta(days=self.period_days)
        patterns = {}

        for symbol in self.symbols:
            print(f"\n🔎 Сбор данных для {symbol} ({start_time.date()} — {end_time.date()})")
            # Исторические свечи
            klines = bybit_client.get_klines(symbol, interval="1h", start_time=start_time, end_time=end_time)
            # Рыночные данные CMC
            cmc_data = get_coinmarketcap_data(symbol)
            # Индекс страха и жадности
            fgi_data = get_fear_greed_index()
            # TVL по цепочке
            chain = self.get_chain_from_symbol(symbol)
            tvl_history = self.defillama.get_chain_tvl(chain) if chain else None

            patterns[symbol] = {
                "klines": klines,
                "cmc": cmc_data,
                "fgi": fgi_data,
                "tvl": tvl_history,
            }
        return patterns

    @staticmethod
    def get_chain_from_symbol(symbol):
        # Пример: ARBUSDT -> Arbitrum, ETHUSDT -> Ethereum
        if symbol.startswith("ARB"):
            return "arbitrum"
        if symbol.startswith("ETH"):
            return "ethereum"
        # ...добавьте свои правила...
        return None

# Пример использования:
if __name__ == "__main__":
    symbols = ["NEWTUSDT", "TREEUSDT", "MPLXUSDT"]
    collector = PatternCollector(symbols)
    data = collector.collect()
    # data теперь содержит всю информацию для дальнейшего анализа паттернов