from data_fetcher import get_klines_data, get_current_price, get_coinmarketcap_data, get_fear_greed_index, get_orderbook_data
from analyzer import analyze_market_data, analyze_fear_greed, analyze_sma_signals, analyze_orderbook, print_summary_table
from models import ConfigManager
from config import SYMBOLS

def main():
    """Основная функция - анализирует все монеты из списка"""
    print(f"🔍 ЗАПУСК МНОГОМОНЕТНОГО АНАЛИЗA ({len(SYMBOLS)} монет)")
    print("=" * 60)
    
    print("🔍 Получение Fear and Greed Index...")
    fgi_data = get_fear_greed_index(30)
    fgi_score = analyze_fear_greed(fgi_data) if fgi_data else 0
    
    config_manager = ConfigManager()
    results = []
    
    for symbol in SYMBOLS:
        print(f"\n📊 АНАЛИЗ {symbol}")
        print("-" * 40)
        
        try:
            df = get_klines_data(symbol)
            if df is None:
                continue
            
            config = config_manager.get_config(symbol, df)
            
            current_price = get_current_price(symbol)
            if current_price is None:
                continue
            
            print("🔍 Получение рыночных данных...")
            market_data = get_coinmarketcap_data(symbol)
            cmc_score = analyze_market_data(market_data, symbol) if market_data else 0
            
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
                
        except Exception as e:
            print(f"❌ Ошибка анализа {symbol}: {e}")
            continue
    
    print_summary_table(results)
    
    print("\n⚙️ ИСПОЛЬЗОВАННЫЕ КОНФИГУРАЦИИ:")
    for symbol, config in config_manager.configs.items():
        print(f"   {symbol}: WHALE_SIZE={config.whale_size:,}, LEVELS={config.orderbook_levels}")

if __name__ == "__main__":
    main()