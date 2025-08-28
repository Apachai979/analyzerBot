import logging
import time
from datetime import datetime, timedelta
from data_fetcher import get_klines_data, get_current_price, get_coinmarketcap_data, get_fear_greed_index, get_orderbook_data
from analyzer import analyze_market_data, analyze_fear_greed, analyze_sma_signals, analyze_orderbook, print_summary_table
from models import ConfigManager
from config import SYMBOLS

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

def main():
    print(f"🔍 ЗАПУСК МНОГОМОНЕТНОГО АНАЛИЗА ({len(SYMBOLS)} монет)")
    print("=" * 60)
    logging.info("Запуск анализа для %d монет", len(SYMBOLS))

    config_manager = ConfigManager()
    last_fgi_update = datetime.min
    fgi_data = None
    fgi_score = 0
    
    last_cmc_update = datetime.min
    cmc_data_cache = {}
    
    while True:
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

        results = []
        for symbol in SYMBOLS:
            print(f"\n📊 АНАЛИЗ {symbol}")
            print("-" * 40)
            logging.info("Анализ %s", symbol)
            try:
                df = get_klines_data(symbol)
                if df is None:
                    logging.warning("Нет данных по свечам для %s", symbol)
                    continue

                config = config_manager.get_config(symbol, df)

                current_price = get_current_price(symbol)
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
                    if symbol == SYMBOLS[0]:  # обновляем время только один раз за цикл
                        last_cmc_update = now
                else:
                    print("Используются кэшированные рыночные данные (CoinMarketCap)")
                    market_data = cmc_data_cache[symbol]
                # ----------------------------------------

                cmc_score = analyze_market_data(market_data, symbol) if market_data else 0
                logging.info("CMC score для %s: %s", symbol, cmc_score)

                analysis_result = analyze_sma_signals(df, current_price, symbol, config, cmc_score, fgi_score)

                orderbook_data = get_orderbook_data(symbol, config)
                if orderbook_data and current_price:
                    bids, asks, bid_volume, ask_volume, whale_bids, whale_asks = orderbook_data
                    analyze_orderbook(bids, asks, bid_volume, ask_volume, whale_bids, whale_asks, current_price, config)

                if analysis_result:
                    results.append({
                        'symbol': symbol,
                        'price': current_price,
                        'signal': analysis_result.get('signal', 'NEUTRAL'),
                        'score': analysis_result.get('score', 0),
                        'trend': analysis_result.get('trend', 'SIDEWAYS'),
                        'cmc_score': analysis_result.get('cmc_score', 0),
                        'fgi_score': analysis_result.get('fgi_score', 0)
                    })
                    logging.info("Результат анализа %s: %s", symbol, analysis_result)

            except Exception as e:
                print(f"❌ Ошибка анализа {symbol}: {e}")
                logging.error("Ошибка анализа %s: %s", symbol, e)
                continue

        print_summary_table(results)
        logging.info("Анализ завершён. Всего результатов: %d", len(results))

        print("\n⚙️ ИСПОЛЬЗОВАННЫЕ КОНФИГУРАЦИИ:")
        for symbol, config in config_manager.configs.items():
            print(f"   {symbol}: WHALE_SIZE={config.whale_size:,}, LEVELS={config.orderbook_levels}")
            logging.info("Конфиг %s: WHALE_SIZE=%s, LEVELS=%s", symbol, config.whale_size, config.orderbook_levels)

        print(f"\n⏳ Следующий анализ через {ANALYSIS_INTERVAL} секунд...\n")
        time.sleep(ANALYSIS_INTERVAL)

if __name__ == "__main__":
    main()