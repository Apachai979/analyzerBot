import threading
import time
from datetime import datetime, timedelta

from bybit_client import bybit_client  # Для стакана, цен и исторических данных
from coinmarketcap_client import get_coinmarketcap_data, get_fear_greed_index
from analyzer import send_telegram_signals, analyze_market_data, analyze_fear_greed, analyze_sma_signals, analyze_orderbook, print_summary_table
from models import ConfigManager
from config import get_token_from_symbol, CHAIN_TO_TOKEN_MAP
from defillama_client import DefiLlamaClient
from tvl_analyzer import TVLAnalyzer
from telegram_utils import send_telegram_message
from spot_trend_watcher import spot_trend_watcher_loop, new_pairs_watcher_loop
from analyzes.multi_timeframe_ma_analysis import full_multi_timeframe_analysis 
from analyzes.atr_rsi_stochastic import full_atr_rsi_sto_multi_analysis, calculate_stochastic, calculate_rsi

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
    with open("dynamic_symbols.txt", "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def main():
    send_telegram_message("BDSMTRADEBOT ACTIVATED!")
    symbols = load_dynamic_symbols()
    print(f"🔍 ЗАПУСК МНОГОМОНЕТНОГО АНАЛИЗА ({len(symbols)} монет)")
    print("=" * 60)
    logging.info("Запуск анализа для %d монет", len(symbols))

    # Запускаем мониторинг трендов спотовых пар и новых пар в отдельных потоках
    threading.Thread(target=spot_trend_watcher_loop, daemon=True).start()
    # threading.Thread(target=new_pairs_watcher_loop, daemon=True).start()

    config_manager = ConfigManager()
    last_fgi_update = datetime.min
    fgi_data = None
    fgi_score = 0

    last_cmc_update = datetime.min
    cmc_data_cache = {}

    defillama = DefiLlamaClient()
    tvl_analyzer = TVLAnalyzer()

    # Получаем TVL данные
    total_tvl_data = defillama.get_total_tvl()
    current_tvl_data = defillama.get_current_tvl()

    # Анализируем общий тренд TVL
    tvl_trend_score = tvl_analyzer.analyze_total_tvl(total_tvl_data)
    chain_rotation = tvl_analyzer.analyze_chain_rotation(current_tvl_data)

    while True:
        symbols = load_dynamic_symbols()
        results = []
        for symbol in symbols:
            print(f"\n📊 АНАЛИЗ {symbol}")
            print("-" * 40)
            logging.info("Анализ %s", symbol)
            try:
                df = bybit_client.get_klines(symbol)
                time.sleep(0.25)

                # Получаем цену и CMC-данные для всех монет
                current_price = bybit_client.get_current_price(symbol)
                time.sleep(0.25)
                now = datetime.now()
                if (
                    symbol not in cmc_data_cache or
                    (now - last_cmc_update).total_seconds() > CMC_UPDATE_INTERVAL
                ):
                    print("🔍 Получение рыночных данных...")
                    market_data = get_coinmarketcap_data(symbol)
                    cmc_data_cache[symbol] = market_data
                    if symbol == symbols[0]:
                        last_cmc_update = now
                else:
                    print("Используются кэшированные рыночные данные (CoinMarketCap)")
                    market_data = cmc_data_cache[symbol]
                cmc_score = analyze_market_data(market_data, symbol) if market_data else 0

                note = ""
                # --- Обработка новых монет с короткой историей ---
                if df is None or len(df) < 100:
                    note = "Недостаточно свечей для тех. анализа"
                    # TVL анализ (коротко, без подробного вывода)
                    chain = get_token_from_symbol(symbol)
                    chain_score = 0
                    if chain and chain in chain_rotation:
                        chain_score = chain_rotation[chain]['score']
                    tvl_score = min(15, tvl_trend_score + chain_score)
                    total_score = min(25, cmc_score) + min(20, fgi_score) + tvl_score
                    results.append({
                        'symbol': symbol,
                        'price': current_price,
                        'signal': "N/A",
                        'score': total_score,
                        'trend': "N/A",
                        'cmc_score': cmc_score,
                        'fgi_score': fgi_score,
                        'tvl_score': tvl_score,
                        'note': note
                    })
                    print(f"⚠️ {symbol}: {note}")
                    continue
                # -------------------------------------------------

                config = config_manager.get_config(symbol, df)
                analysis_result = analyze_sma_signals(df, current_price, symbol, config, cmc_score, fgi_score)

                orderbook_data = bybit_client.get_orderbook(symbol, config.orderbook_levels, config.whale_size)
                time.sleep(0.25)
                if orderbook_data and current_price:
                    bids, asks, bid_volume, ask_volume, whale_bids, whale_asks = orderbook_data
                    analyze_orderbook(bids, asks, bid_volume, ask_volume, whale_bids, whale_asks, current_price, config)

                if analysis_result:
                    chain = get_token_from_symbol(symbol)
                    chain_score = 0
                    if chain and chain in chain_rotation:
                        chain_score = chain_rotation[chain]['score']
                    tvl_score = min(15, tvl_trend_score + chain_score)
                    total_score = (
                        analysis_result.get('score', 0) +
                        min(25, cmc_score) +
                        min(20, fgi_score) +
                        tvl_score +
                        analysis_result.get('bonus_score', 0)
                    )

                    # --- TVL анализ: подробный вывод ---
                    chain_name = chain if chain else "Unknown"
                    chain_info = chain_rotation.get(chain_name, {})
                    chain_change = chain_info.get('change_24h', 0)
                    chain_score = chain_info.get('score', 0)

                    tvl_7d_change = None
                    if total_tvl_data and len(total_tvl_data) >= 8:
                        tvl_7d_change = (total_tvl_data[-1]['tvl'] - total_tvl_data[-8]['tvl']) / total_tvl_data[-8]['tvl'] * 100

                    if tvl_7d_change is not None:
                        tvl_trend_str = f"{tvl_7d_change:+.1f}% за 7 дней → {tvl_trend_score:+d} очков"
                    else:
                        tvl_trend_str = f"{tvl_trend_score:+d} очков"

                    chain_tvl_str = f"{chain_change:+.1%} за 24h → {chain_score:+d} очков для {chain_name}" if chain else ""
                    if chain_score > 20:
                        logging.info(f"🚀 Капитал перетекает в {chain_name} - сигнал к покупке {symbol}")
                    if tvl_trend_score < -15 and analysis_result.get('price_change_7d', 0) > 0:
                        logging.info("📉 TVL падает, но цена держится - возможен разворот")

                    if chain_rotation:
                        best_chain = max(chain_rotation.items(), key=lambda x: x[1]['score'])
                        token_symbol = CHAIN_TO_TOKEN_MAP.get(best_chain[0], "") + "USDT"
                        logging.info(f"🔄 Ротация в {best_chain[0]} - рассматриваем {token_symbol}")

                    print(f"📊 TVL АНАЛИЗ:")
                    print(f"   {'📈' if tvl_trend_score > 0 else '📉'} Общий TVL: {tvl_trend_str}")
                    if chain:
                        print(f"   {'🚀' if chain_score > 20 else '🔻' if chain_score < 0 else '🔄'} {chain_name} TVL: {chain_tvl_str}")
                        if chain_score > 20:
                            print(f"   🔄 Капитал перетекает в {chain_name}")
                        elif chain_score < 0:
                            print(f"   💸 Капитал уходит из {chain_name}")
                    print()
                    print(f"🎯 ИТОГОВЫЙ SCORE {symbol}: {total_score}/100 ({'+' if tvl_score >= 0 else ''}{tvl_score} от TVL)")
                    # --- конец подробного TVL-анализа ---

                    results.append({
                        'symbol': symbol,
                        'price': current_price,
                        'signal': analysis_result.get('signal', 'NEUTRAL'),
                        'score': total_score,
                        'trend': analysis_result.get('trend', 'SIDEWAYS'),
                        'cmc_score': analysis_result.get('cmc_score', 0),
                        'fgi_score': analysis_result.get('fgi_score', 0),
                        'tvl_score': tvl_score,
                        'note': ""
                    })
                    logging.info("Результат анализа %s: %s", symbol, analysis_result)

            except Exception as e:
                print(f"❌ Ошибка анализа {symbol}: {e}")
                logging.error("Ошибка анализа %s: %s", symbol, e)
                continue

        print_summary_table(results)
        send_telegram_signals(results)
        for res in results:
            if 'note' in res and res['note']:
                print(f"⚠️ {res['symbol']}: {res['note']}")
        logging.info("Анализ завершён. Всего результатов: %d", len(results))
        print(f"\n⏳ Следующий анализ через {ANALYSIS_INTERVAL} секунд...\n")
        time.sleep(ANALYSIS_INTERVAL)

if __name__ == "__main__":
    # main()
    # print(bybit_client.get_coin_info("FLOCK"))
    # market_data = get_coinmarketcap_data('FLOCK')
    # print(market_data)
    df_1h = bybit_client.get_klines('FLOCKUSDT', interval='60')
    df_4h = bybit_client.get_klines('FLOCKUSDT', interval='240')
    
    df_dict = {"1h": df_1h, "4h": df_4h}
    full_atr_rsi_sto_multi_analysis(df_dict,symbol='FLOCKUSDT')

    
     

    # result = full_multi_timeframe_analysis(
    #     df_dict,
    #     fast_period=9,
    #     slow_period=21,
    #     lookback_periods=50,
    #     bb_period=20,
    #     bb_num_std=2,
    #     symbol="FLOCKUSDT"
    # )
    # print(result)