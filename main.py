import threading
import time
from datetime import datetime, timedelta

from bybit_client import bybit_client
from orderbook_analyzer import analyze_orderbook
from coinmarketcap_client import get_coinmarketcap_data, get_fear_greed_index, analyze_fgi_trend
from config_manager import ConfigManager
from defillama_client import DefiLlamaClient, analyze_tvl
from telegram_utils import send_telegram_message
from spot_trend_watcher import spot_trend_watcher_loop, new_pairs_watcher_loop
from analyzes.multi_timeframe_ma_analysis import full_multi_timeframe_analysis 
from analyzes.atr_rsi_stochastic import full_atr_rsi_sto_multi_analysis, calculate_stochastic, calculate_rsi
from chain_market_analyzer import analyze_chains_and_market

import logging

logging.basicConfig(
    filename='analyzer.log',
    filemode='a',
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)

FGI_UPDATE_INTERVAL = 60 * 60 * 12  # 12 часов
ANALYSIS_INTERVAL = 60  # 1 минута
CMC_UPDATE_INTERVAL = 60 * 30  # 30 минут

def load_dynamic_symbols():
    with open("data/dynamic_symbols.txt", "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def main():
    
    send_telegram_message("BDSMTRADEBOT ACTIVATED!")
    
    symbols = load_dynamic_symbols()
    print(f"🔍 ЗАПУСК МНОГОМОНЕТНОГО АНАЛИЗА ({len(symbols)} монет)")
    print("=" * 60)
    
    cmc_data = get_coinmarketcap_data(symbols=load_dynamic_symbols())
    analysis_results = analyze_chains_and_market(cmc_data)
    for res in analysis_results:
        print(res['chain'], res['token'], res['tvl_trend'], res['recommendations'])
    
    # Запускаем мониторинг трендов спотовых пар и новых пар в отдельных потоках
    # threading.Thread(target=spot_trend_watcher_loop, daemon=True).start()

    config_manager = ConfigManager()

    while True:
        symbols = load_dynamic_symbols()
        results = []
        for symbol in symbols:
            try:
                df_1h = bybit_client.get_klines(symbol, interval='60')
                # df_4h = bybit_client.get_klines(symbol, interval='240')
                df_dict = {'1h': df_1h}
                result = full_multi_timeframe_analysis(
                    df_dict,
                    fast_period=9,
                    slow_period=21,
                    lookback_periods=50,
                    bb_period=20,
                    bb_num_std=2,
                    symbol="FLOCKUSDT"
                )
                print(result)   
                full_atr_rsi_sto_multi_analysis(df_dict, symbol=symbol)
                
                time.sleep(0.25)

                config = config_manager.get_config(symbol, df_1h)

                orderbook_data = bybit_client.get_orderbook(symbol, config.orderbook_levels, config.whale_size)
                
                time.sleep(0.25)
                
                current_price = bybit_client.get_current_price(symbol)
                
                if orderbook_data and current_price:
                    bids, asks, bid_volume, ask_volume, whale_bids, whale_asks = orderbook_data
                    analyze_orderbook(bids, asks, bid_volume, ask_volume, whale_bids, whale_asks, current_price, config)
                 
                time.sleep(2000)

            except Exception as e:
                print(f"❌ Ошибка анализа {symbol}: {e}")
                logging.error("Ошибка анализа %s: %s", symbol, e)
                continue

if __name__ == "__main__":
    main()