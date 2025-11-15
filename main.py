import threading
import time
from datetime import datetime, timedelta
import os
import logging

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
from time_frame_tracker import TimeframeAnalysisTracker

# Настройка логирования
logging.basicConfig(
    filename='analyzer.log',
    filemode='a',
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)


def load_dynamic_symbols():
    with open("data/filtered_symbols.txt", "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def main():
    
    timeUTC = bybit_client.get_server_time()
    config_manager = ConfigManager()
    tracker = TimeframeAnalysisTracker()
    
    # Пауза между полными циклами (в секундах)
    CYCLE_PAUSE = 60  # 1 минута - проверяем часто, но сам анализ контролируется tracker
    
    logging.info("="*60)
    logging.info("🚀 Бот запущен. Начало работы.")
    logging.info(f"UTC время сервера: {timeUTC.get('datetime_utc')}")
    logging.info("="*60)

    while True:
        cycle_start = time.time()
        symbols = load_dynamic_symbols()
        
        for symbol in symbols:
            try:
                # 1D анализ - каждые 12 часов
                if not tracker.should_analyze(symbol, '1D'):
                    continue  # Пропускаем, если еще рано
                
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
                    
                    # Получаем action от MACD
                    macd_action = one_d_analyze_result.get("macd_action")
                    
                    all_buy = (
                        (ema_verdict == "STRONG_BUY" or ema_verdict == "CAUTIOUS_BUY") and 
                        macd_action == "BUY" and 
                        volume_action == "BUY"
                    )
                    
                    all_sell = (
                        ema_verdict == "STRONG_SELL" and 
                        macd_action == "SELL" and 
                        volume_action == "BUY"  # Volume BUY = есть движение/объем
                    )
                    
                    if all_buy or all_sell:
                        signal_type = "🟢 ПОКУПАТЬ" if all_buy else "🔴 ПРОДАВАТЬ"
                        trend_1d = "BULLISH" if all_buy else "BEARISH"
                        
                        logging.info(f"[1D] {symbol} → {signal_type} (trend: {trend_1d})")
                        
                        # send_telegram_message(
                        #     f"⚡ {signal_type}\n[1D] {symbol}\n{one_d_analyze_result.get('summary', '')}"
                        # )
                        
                        # 12H анализ - каждые 4 часа (только если есть сигнал 1D)
                        if not tracker.should_analyze(symbol, '12H'):
                            continue  # Еще рано для 12H анализа
                        
                        # Анализ 12H с учетом тренда 1D
                        df_12h = bybit_client.get_klines(symbol, interval='720')
                        twelve_h_result = analyze_12h_correction_strategy(df_12h, trend_1d=trend_1d, symbol=symbol)
                        
                        if twelve_h_result:
                            print(f"[12H] {symbol}\n{twelve_h_result.get('summary', '')}")
                            
                            twelve_h_action = twelve_h_result.get('action')
                            logging.info(f"[12H] {symbol} → {twelve_h_action}")
                            
                            # Если 12H дает GO или ATTENTION - переходим на 4H
                            if twelve_h_action in ['GO', 'ATTENTION']:
                                # send_telegram_message(
                                #     f"{'🟢' if twelve_h_action == 'GO' else '🟡'} 12H СИГНАЛ!\n{symbol}\n{twelve_h_result.get('summary', '')}"
                                # )
                                
                                # 4H анализ - каждые 2 часа (только если 12H дал GO/ATTENTION)
                                if not tracker.should_analyze(symbol, '4H'):
                                    continue  # Еще рано для 4H анализа
                                
                                # Анализ 4H - тактический фильтр для перехода к 1H
                                df_4h = bybit_client.get_klines(symbol, interval='240')
                                four_h_result = analyze_4h_entry_strategy(df_4h, trend_1d=trend_1d, twelve_h_signal=twelve_h_result, symbol=symbol)
                                
                                if four_h_result:
                                    print(f"[4H] {symbol}\n{four_h_result.get('summary', '')}")
                                    
                                    four_h_action = four_h_result.get('action')
                                    logging.info(f"[4H] {symbol} → {four_h_action}")
                                    
                                    # Если 4H дает GO или ATTENTION - анализируем 1H для точного входа
                                    if four_h_action in ['GO', 'ATTENTION']:
                                        # Отправляем 4H сигнал (с дедупликацией)
                                        if tracker.should_send_signal(symbol, four_h_action, '4H'):
                                            send_telegram_message(
                                                f"{'✅' if four_h_action == 'GO' else '⚠️'} 4H {'ГОТОВНОСТЬ' if four_h_action == 'GO' else 'ОСТОРОЖНО'}!\n{symbol}\n{four_h_result.get('summary', '')}"
                                            )
                                        
                                        # 1H анализ - каждые 15 минут (только если 4H дал GO/ATTENTION)
                                        if not tracker.should_analyze(symbol, '1H'):
                                            continue  # Еще рано для 1H анализа
                                        
                                        # Анализ 1H для точного входа
                                        df_1h = bybit_client.get_klines(symbol, interval='60')
                                        one_h_result = analyze_1h_execution(df_1h, four_h_signal=four_h_result, trend_1d=trend_1d, symbol=symbol)
                                        
                                        if one_h_result:
                                            print(f"[1H] {symbol}\n{one_h_result.get('summary', '')}")
                                            
                                            one_h_action = one_h_result.get('action')
                                            logging.info(f"[1H] {symbol} → {one_h_action}")
                                            
                                            # Отправляем 1H сигналы (с дедупликацией)
                                            if one_h_action == 'ENTER':
                                                if tracker.should_send_signal(symbol, 'ENTER', '1H'):
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
                                            
                                            elif one_h_action == 'WAIT_BETTER':
                                                if tracker.should_send_signal(symbol, 'WAIT_BETTER', '1H'):
                                                    send_telegram_message(
                                                        f"🟡 1H ЖДАТЬ ЛУЧШЕЙ ЦЕНЫ!\n{symbol}\n{one_h_result.get('summary', '')}"
                                                    )
                                            
                                            elif one_h_action == 'SKIP':
                                                if tracker.should_send_signal(symbol, 'SKIP', '1H'):
                                                    send_telegram_message(
                                                        f"🔴 1H ПРОПУСТИТЬ!\n{symbol}\n{one_h_result.get('summary', '')}"
                                                    )

            except Exception as e:
                error_msg = f"❌ Ошибка анализа {symbol}: {e}"
                print(error_msg)
                logging.error(error_msg)
                continue
        
        # Пауза между циклами
        cycle_duration = time.time() - cycle_start
        print(f"\n⏱️  Цикл завершен за {cycle_duration:.1f}s. Пауза {CYCLE_PAUSE}s...\n")
        time.sleep(CYCLE_PAUSE)

if __name__ == "__main__":
    # print(timeUTC.get('datetime_utc'))
    main()