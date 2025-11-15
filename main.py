import threading
import time
from datetime import datetime, timedelta
import os

from analyzes.time_frame_analysis import (analyze_1d_ma_macd_volume, analyze_12h_correction_strategy, analyze_4h_entry_strategy, analyze_1h_execution, analyze_15m_stoch_ema_volume)
from ai_generate import ask_deepseek
from bybit_client import bybit_client
from orderbook_analyzer import analyze_orderbook
from coinmarketcap_client import get_coinmarketcap_data, get_fear_greed_index, analyze_fgi_trend
from config_manager import ConfigManager
from defillama_client import DefiLlamaClient, analyze_tvl
from telegram_utils import send_telegram_message
from chain_market_analyzer import analyze_chains_and_market
from analyzes.analytics_center import handle_12h_correction_buy_signal

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
    with open("data/filtered_symbols.txt", "r", encoding="utf-8") as f:
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
    # send_telegram_message("BDSMTRADEBOT ACTIVATED!")
    # symbols = load_dynamic_symbols()
    # print(f"🔍 ЗАПУСК МНОГОМОНЕТНОГО АНАЛИЗА ({len(symbols)} монет)")
    # print("=" * 60)

    # threading.Thread(target=periodic_chain_analysis, daemon=True).start()
    # # Запускаем мониторинг трендов спотовых пар и новых пар в отдельных потоках
    
    # threading.Thread(target=spot_trend_watcher_loop, daemon=True).start()
    
    # threading.Thread(target=periodic_fgi_analysis, daemon=True).start() 
    
    config_manager = ConfigManager()

    while True:
        symbols = load_dynamic_symbols()
        for symbol in symbols:
            try:
                df_D = bybit_client.get_klines(symbol, interval='D')
                one_d_analyze_result = analyze_1d_ma_macd_volume(df_D, symbol)
                if one_d_analyze_result:
                    print(f"[1D] {symbol}\n{one_d_analyze_result.get('summary', '')}")
                    
                    # Извлекаем сигналы для принятия решения
                    ema_result = one_d_analyze_result.get("ema_result")
                    volume_result = one_d_analyze_result.get("volume_result")
                    
                    # Получаем trading_verdict от EMA
                    ema_verdict = ema_result.get('trading_verdict') if ema_result else None
                    
                    # Получаем action от Volume
                    volume_action = volume_result.get('action') if volume_result else None
                    
                    # Получаем action от MACD (нужно получить из analyze_1d_ma_macd_volume)
                    # Предполагаем, что в one_d_analyze_result есть macd_action
                    macd_action = one_d_analyze_result.get("macd_action")
                    
                    # Проверяем условия для отправки сообщения
                    # Volume теперь только BUY (есть движение) или WAIT (нет движения)
                    # Поэтому проверяем только наличие движения
                    all_buy = (
                        (ema_verdict == "STRONG_BUY" or ema_verdict == "CAUTIOUS_BUY") and 
                        macd_action == "BUY" and 
                        volume_action == "BUY"  # Есть движение
                    )
                    
                    all_sell = (
                        ema_verdict == "STRONG_SELL" and 
                        macd_action == "SELL" and 
                        volume_action == "BUY"  # Есть движение (не SELL, т.к. volume не определяет направление)
                    )
                    
                    if all_buy or all_sell:
                        signal_type = "🟢 ПОКУПАТЬ" if all_buy else "🔴 ПРОДАВАТЬ"
                        trend_1d = "BULLISH" if all_buy else "BEARISH"
                        
                        # send_telegram_message(
                        #     f"⚡ {signal_type}\n[1D] {symbol}\n{one_d_analyze_result.get('summary', '')}"
                        # )
                        time.sleep(3)
                        
                        # Анализ 12H с учетом тренда 1D
                        df_12h = bybit_client.get_klines(symbol, interval='720')
                        twelve_h_result = analyze_12h_correction_strategy(df_12h, trend_1d=trend_1d, symbol=symbol)
                        
                        if twelve_h_result:
                            print(f"[12H] {symbol}\n{twelve_h_result.get('summary', '')}")
                            
                            # Если 12H дает GO или ATTENTION - переходим на 4H
                            if twelve_h_result.get('action') in ['GO', 'ATTENTION']:
                                send_telegram_message(
                                    f"{'🟢' if twelve_h_result.get('action') == 'GO' else '🟡'} 12H СИГНАЛ!\n{symbol}\n{twelve_h_result.get('summary', '')}"
                                )
                                time.sleep(3)
                                
                                # Анализ 4H - тактический фильтр для перехода к 1H
                                df_4h = bybit_client.get_klines(symbol, interval='240')
                                four_h_result = analyze_4h_entry_strategy(df_4h, trend_1d=trend_1d, twelve_h_signal=twelve_h_result, symbol=symbol)
                                
                                if four_h_result:
                                    print(f"[4H] {symbol}\n{four_h_result.get('summary', '')}")
                                    
                                    # Если 4H дает GO или ATTENTION - анализируем 1H для точного входа
                                    if four_h_result.get('action') in ['GO', 'ATTENTION']:
                                        send_telegram_message(
                                            f"{'✅' if four_h_result.get('action') == 'GO' else '⚠️'} 4H {'ГОТОВНОСТЬ' if four_h_result.get('action') == 'GO' else 'ОСТОРОЖНО'}!\n{symbol}\n{four_h_result.get('summary', '')}"
                                        )
                                        time.sleep(5)
                                        
                                        # Анализ 1H для точного входа
                                        df_1h = bybit_client.get_klines(symbol, interval='60')
                                        one_h_result = analyze_1h_execution(df_1h, four_h_signal=four_h_result, trend_1d=trend_1d, symbol=symbol)
                                        
                                        if one_h_result:
                                            print(f"[1H] {symbol}\n{one_h_result.get('summary', '')}")
                                            
                                            # Если 1H дает ENTER - отправляем сигнал на вход
                                            if one_h_result.get('action') == 'ENTER':
                                                entry_price = one_h_result.get('entry_price', 0)
                                                stop_loss = one_h_result.get('stop_loss', 0)
                                                take_profit = one_h_result.get('take_profit', 0)
                                                risk_percent = one_h_result.get('risk_percent', 0)
                                                
                                                send_telegram_message(
                                                    f"🎯 1H ВХОД В СДЕЛКУ!\n"
                                                    f"{symbol}\n"
                                                    f"Направление: {'LONG' if trend_1d == 'BULLISH' else 'SHORT'}\n"
                                                    f"Вход: {entry_price:.4f}\n"
                                                    f"Стоп: {stop_loss:.4f}\n"
                                                    f"Тейк: {take_profit:.4f}\n"
                                                    f"Риск: {risk_percent:.2f}%\n"
                                                    f"R:R = 1:2\n\n"
                                                    f"{one_h_result.get('summary', '')}"
                                                )
                                                time.sleep(5)
                                            
                                            elif one_h_result.get('action') == 'WAIT_BETTER':
                                                send_telegram_message(
                                                    f"🟡 1H ЖДАТЬ ЛУЧШЕЙ ЦЕНЫ!\n{symbol}\n{one_h_result.get('summary', '')}"
                                                )
                                                time.sleep(3)
                                            
                                            elif one_h_result.get('action') == 'SKIP':
                                                send_telegram_message(
                                                    f"🔴 1H ПРОПУСТИТЬ!\n{symbol}\n{one_h_result.get('summary', '')}"
                                                )
                                                time.sleep(3)
                            
                            elif twelve_h_result.get('action') == 'ATTENTION':
                                send_telegram_message(
                                    f"🟡 12H ВНИМАНИЕ!\n{symbol}\n{twelve_h_result.get('summary', '')}"
                                )
                                time.sleep(3)

                time.sleep(4)

            except Exception as e:
                print(f"❌ Ошибка анализа {symbol}: {e}")
                logging.error("Ошибка анализа %s: %s", symbol, e)
                time.sleep(10)
                continue

if __name__ == "__main__":
    main()