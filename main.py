import threading
import time
from datetime import datetime, timedelta
import os

from ai_generate import ask_deepseek
from bybit_client import bybit_client
from orderbook_analyzer import analyze_orderbook
from coinmarketcap_client import get_coinmarketcap_data, get_fear_greed_index, analyze_fgi_trend
from config_manager import ConfigManager
from defillama_client import DefiLlamaClient, analyze_tvl
from telegram_utils import send_telegram_message
from spot_trend_watcher import spot_trend_watcher_loop
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

def periodic_fgi_analysis(interval_sec=60*60*12, log_path="logs/fgi_analysis_log.txt"):
    last_run = 0
    while True:
        try:
            current_time = time.time()
            if current_time - last_run > interval_sec:
                from coinmarketcap_client import get_fear_greed_index, analyze_fgi_trend
                fgi_data = get_fear_greed_index()
                fgi_analysis = analyze_fgi_trend(fgi_data)
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(f"{datetime.now()} | FGI Анализ: {fgi_analysis}\n")
                last_run = current_time
            time.sleep(60)
        except Exception as e:
            print(f"❌ Ошибка периодического FGI-анализа: {e}")
            logging.error("Ошибка периодического FGI-анализа: %s", e)
            time.sleep(90)

def get_last_fgi_analysis(log_path="logs/fgi_analysis_log.txt"):
    if not os.path.exists(log_path):
        return ""
    with open(log_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
        if lines:
            return lines[-1]
    return ""

def save_chain_analysis_results(analysis_results, log_path="logs/chain_market_analysis.txt"):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        for res in analysis_results:
            line = (
                f"Блокчейн: {res['chain']} | "
                f"Монета: {res['token']} | "
                f"Название: {res.get('token_name', '')} | "
                f"TVL: {res.get('tvl', 0):,.0f} | "
                f"Цена: {res.get('price', 0):.6f} | "
                f"Объем 24ч: {res.get('volume_24h', 0):,.0f} | "
                f"Капитализация: {res.get('market_cap', 0):,.0f} | "
                f"Изм. 24ч: {res.get('percent_change_24h', 'N/A')} | "
                f"Изм. 7д: {res.get('percent_change_7d', 'N/A')} | "
                f"Изм. 30д: {res.get('percent_change_30d', 'N/A')} | "
                f"TVL/Объем: {res.get('volume_tvl_ratio', 'N/A')} | "
                f"TVL/Цена: {res.get('price_tvl_ratio', 'N/A')} | "
                f"TVL/Капитализация: {res.get('mcap_tvl_ratio', 'N/A')} | "
                f"Тренд TVL: {res['tvl_trend']} | "
                f"Рекомендации: {res['recommendations']}\n"
            )
            f.write(line)

def periodic_chain_analysis(symbols_file="data/dynamic_symbols.txt", interval_sec=7200):
    last_run = 0
    last_mtime = 0
    while True:
        try:
            current_time = time.time()
            current_mtime = os.path.getmtime(symbols_file)
            # Проверяем: прошло ли 2 часа или изменился файл
            if (current_time - last_run > interval_sec) or (current_mtime != last_mtime):
                symbols = load_dynamic_symbols()
                cmc_data = get_coinmarketcap_data(symbols=symbols)
                analysis_results = analyze_chains_and_market(cmc_data)
                save_chain_analysis_results(analysis_results)
                last_run = current_time
                last_mtime = current_mtime
            time.sleep(60)  # Проверяем каждые 30 секунд
        except Exception as e:
            print(f"❌ Ошибка периодического анализа: {e}")
            logging.error("Ошибка периодического анализа: %s", e)
            time.sleep(90)

def get_chain_summary_from_file(symbol, log_path="logs/chain_market_analysis.txt"):
    token = symbol.replace("USDT", "")
    if not os.path.exists(log_path):
        return ""
    summaries = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            if f"Монета: {token} |" in line:
                summaries.append(line.strip())
    return "\n".join(summaries)

def format_coin_summary(symbol, ma_analysis, atr_rsi_sto_analysis, orderbook_conclusions, chain_analysis, fgi_info):
    """
    Формирует итоговый текстовый блок по результатам анализа монеты.
    Все аргументы — строки или заранее подготовленные блоки.
    """
    summary = []
    summary.append(f"{datetime.now()} | {symbol} | ИТОГОВЫЙ АНАЛИЗ\n")
    if ma_analysis:
        summary.append("=== MA/BB/MACD/Объем ===")
        summary.append(ma_analysis)
    if atr_rsi_sto_analysis:
        summary.append("=== ATR/RSI/Stochastic ===")
        summary.append(atr_rsi_sto_analysis)
    if orderbook_conclusions:
        summary.append("=== Order Book ===")
        summary.append(orderbook_conclusions)
    if chain_analysis:
        summary.append("=== Chain/TVL ===")
        summary.append(chain_analysis)
    if fgi_info:
        summary.append("=== Fear & Greed Index ===")
        summary.append(fgi_info)
    summary.append("---\n")
    return "\n".join(summary)

def main():
    send_telegram_message("BDSMTRADEBOT ACTIVATED!")
    symbols = load_dynamic_symbols()
    print(f"🔍 ЗАПУСК МНОГОМОНЕТНОГО АНАЛИЗА ({len(symbols)} монет)")
    print("=" * 60)

    threading.Thread(target=periodic_chain_analysis, daemon=True).start()
    # Запускаем мониторинг трендов спотовых пар и новых пар в отдельных потоках
    threading.Thread(target=spot_trend_watcher_loop, daemon=True).start()
    threading.Thread(target=periodic_fgi_analysis, daemon=True).start() 
    
    config_manager = ConfigManager()

    while True:
        symbols = load_dynamic_symbols()
        for symbol in symbols:
            try:
                df_1h = bybit_client.get_klines(symbol, interval='60')
                df_4h = bybit_client.get_klines(symbol, interval='240')
                df_12h = bybit_client.get_klines(symbol, interval='720')
                df_dict = {'1h': df_1h, '4h': df_4h, '12h': df_12h}

                # MA/BB/MACD/Объем
                ma_result = full_multi_timeframe_analysis(
                    df_dict,
                    fast_period=9,
                    slow_period=21,
                    lookback_periods=50,
                    bb_period=20,
                    bb_num_std=2,
                    symbol=symbol
                )
                ma_summary = ""
                if ma_result:
                    ma_summary = ""
                    for tf in ['1h', '4h', '12h']:
                        if tf in ma_result['results']:
                            res = ma_result['results'][tf]
                            ma_summary += (
                                f"[{tf}] SMA сигнал: {res['sma_signal']}\n"
                                f"[{tf}] EMA сигнал: {res['ema_signal']}\n"
                                f"[{tf}] Bollinger Bands SMA сигнал: {res['bb_sma_signal']}\n"
                                f"[{tf}] Bollinger Bands EMA сигнал: {res['bb_ema_signal']}\n"
                                f"[{tf}] MACD сигнал: {res['macd_signal']}\n"
                                f"[{tf}] Сигнал по объему: {res['volume_signal']}\n"
                            )

                # ATR/RSI/Stochastic
                atr_rsi_sto_result = full_atr_rsi_sto_multi_analysis(df_dict, symbol=symbol)
                atr_rsi_sto_summary = ""
                if atr_rsi_sto_result:
                    for tf in ['1h', '4h', '12h']:
                        if tf in atr_rsi_sto_result:
                            atr = atr_rsi_sto_result[tf]['atr']
                            rsi = atr_rsi_sto_result[tf]['rsi']
                            stoch = atr_rsi_sto_result[tf]['stochastic']
                            atr_rsi_sto_summary += (
                                f"[{tf}] ATR: {atr['current_atr']:.4f}, %: {atr['current_atr_pct']:.2f}, Волатильность: {atr['volatility']}\n"
                                f"[{tf}] RSI: {rsi.iloc[-1]:.2f}\n"
                                f"[{tf}] Stoch %K: {stoch['stoch_k'].iloc[-1]:.2f}, %D: {stoch['stoch_d'].iloc[-1]:.2f}\n"
                            )

                # Order Book
                config = config_manager.get_config(symbol, df_1h)
                orderbook_data = bybit_client.get_orderbook(symbol, config.orderbook_levels, config.whale_size)
                current_price = bybit_client.get_current_price(symbol)
                orderbook_summary = ""
                if orderbook_data and current_price:
                    bids, asks, bid_volume, ask_volume, whale_bids, whale_asks = orderbook_data
                    orderbook_summary = analyze_orderbook(
                        bids, asks, bid_volume, ask_volume, whale_bids, whale_asks, current_price, config, symbol
                    )
                # Chain/TVL
                chain_summary = get_chain_summary_from_file(symbol)
                
                #  Fear & Greed Index 
                fgi_info = get_last_fgi_analysis()
                # Формируем итоговый вывод
                
                summary_text = format_coin_summary(symbol, ma_summary, atr_rsi_sto_summary, orderbook_summary, chain_summary, fgi_info)
                with open("logs/summary_analysis_log.txt", "a", encoding="utf-8") as f:
                    f.write(summary_text)
                ask_deepseek(summary_text, symbol)
                print(summary_text)
                time.sleep(1)
            except Exception as e:
                print(f"❌ Ошибка анализа {symbol}: {e}")
                logging.error("Ошибка анализа %s: %s", symbol, e)
                continue

if __name__ == "__main__":
    main()