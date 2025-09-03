import threading
import time
from datetime import datetime, timedelta

from bybit_client import bybit_client  # Для стакана, цен и исторических данных
from coinmarketcap_client import get_coinmarketcap_data, get_fear_greed_index
from analyzer import analyze_market_data, analyze_fear_greed, analyze_sma_signals, analyze_orderbook, print_summary_table
from models import ConfigManager
from config import get_token_from_symbol, CHAIN_TO_TOKEN_MAP
from defillama_client import DefiLlamaClient
from tvl_analyzer import TVLAnalyzer
from telegram_utils import send_telegram_message
from spot_trend_watcher import spot_trend_watcher_loop, new_pairs_watcher_loop

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
    threading.Thread(target=new_pairs_watcher_loop, daemon=True).start()

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
            now = datetime.now()
            # Обновляем FGI только если прошло 12 часов
            if (now - last_fgi_update).total_seconds() > FGI_UPDATE_INTERVAL or fgi_data is None:
                print("🔍 Получение Fear and Greed Index...")
                fgi_data = get_fear_greed_index(30)
                fgi_score = analyze_fear_greed(fgi_data) if fgi_data else 0
                last_fgi_update = now
                logging.info("FGI обновлен: %s", fgi_score)
            else:
                print("Используется кэшированный FGI (обновится через %.1f ч)" % ((FGI_UPDATE_INTERVAL - (now - last_fgi_update).total_seconds()) / 3600))

            print(f"\n📊 АНАЛИЗ {symbol}")
            print("-" * 40)
            logging.info("Анализ %s", symbol)
            try:
                # Получаем исторические данные через bybit_client
                df = bybit_client.get_klines(symbol)
                if df is None:
                    logging.warning("Нет данных по свечам для %s", symbol)
                    continue

                config = config_manager.get_config(symbol, df)

                current_price = bybit_client.get_current_price(symbol)
                if current_price is None:
                    logging.warning("Не удалось получить цену для %s", symbol)
                    continue

                # --- Кэширование CoinMarketCap данных ---
                if (
                    symbol not in cmc_data_cache or
                    (now - last_cmc_update).total_seconds() > CMC_UPDATE_INTERVAL
                ):
                    print("🔍 Получение рыночных данных...")
                    market_data = get_coinmarketcap_data(symbol)
                    cmc_data_cache[symbol] = market_data
                    if symbol == symbols[0]:  # исправлено!
                        last_cmc_update = now
                else:
                    print("Используются кэшированные рыночные данные (CoinMarketCap)")
                    market_data = cmc_data_cache[symbol]
                # ----------------------------------------

                cmc_score = analyze_market_data(market_data, symbol) if market_data else 0
                logging.info("CMC score для %s: %s", symbol, cmc_score)

                analysis_result = analyze_sma_signals(df, current_price, symbol, config, cmc_score, fgi_score)

                # Получаем стакан через bybit_client
                orderbook_data = bybit_client.get_orderbook(symbol, config.orderbook_levels, config.whale_size)
                if orderbook_data and current_price:
                    bids, asks, bid_volume, ask_volume, whale_bids, whale_asks = orderbook_data
                    analyze_orderbook(bids, asks, bid_volume, ask_volume, whale_bids, whale_asks, current_price, config)

                if analysis_result:
                    # Получаем блокчейн для символа
                    chain = get_token_from_symbol(symbol)
                    chain_score = 0
                    if chain and chain in chain_rotation:
                        chain_score = chain_rotation[chain]['score']

                    # Итоговый TVL score: тренд + ротация (ограничить 15)
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

                    # Общий TVL за 7 дней
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

                    # Находим цепочку с самым быстрым ростом TVL
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

                    results.append({
                        'symbol': symbol,
                        'price': current_price,
                        'signal': analysis_result.get('signal', 'NEUTRAL'),
                        'score': total_score,
                        'trend': analysis_result.get('trend', 'SIDEWAYS'),
                        'cmc_score': analysis_result.get('cmc_score', 0),
                        'fgi_score': analysis_result.get('fgi_score', 0),
                        'tvl_score': tvl_score
                    })
                    logging.info("Результат анализа %s: %s", symbol, analysis_result)

            except Exception as e:
                print(f"❌ Ошибка анализа {symbol}: {e}")
                logging.error("Ошибка анализа %s: %s", symbol, e)
                continue

        print_summary_table(results)
        logging.info("Анализ завершён. Всего результатов: %d", len(results))

        # print("\n⚙️ ИСПОЛЬЗОВАННЫЕ КОНФИГУРАЦИИ:")
        # for symbol, config in config_manager.configs.items():
        #     print(f"   {symbol}: WHALE_SIZE={config.whale_size:,}, LEVELS={config.orderbook_levels}")
        #     logging.info("Конфиг %s: WHALE_SIZE=%s, LEVELS=%s", symbol, config.whale_size, config.orderbook_levels)

        print(f"\n⏳ Следующий анализ через {ANALYSIS_INTERVAL} секунд...\n")
        time.sleep(ANALYSIS_INTERVAL)

if __name__ == "__main__":
    main()