import threading
import time
import os
import logging

from analyzes.time_frame_analysis import (analyze_1d_ma_macd_volume, analyze_12h_correction_strategy, analyze_4h_entry_strategy, analyze_1h_execution)
from bybit_client import bybit_client
from telegram_utils import send_telegram_message, process_telegram_updates, send_emergency_alert
from time_frame_tracker import TimeframeAnalysisTracker
from range_trading import analyze_range_trading_signal

# Настройка логирования
logging.basicConfig(
    filename='analyzer.log',
    filemode='a',
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)

def format_price(price, reference_price):
    """
    Форматирует цену в соответствии с количеством знаков после запятой в reference_price.
    Убирает незначащие нули в конце.
    """
    if price is None or reference_price is None:
        return str(price)
    
    # Определяем количество знаков после запятой в reference_price
    ref_str = f"{reference_price:.15f}".rstrip('0').rstrip('.')
    if '.' in ref_str:
        decimal_places = len(ref_str.split('.')[1])
    else:
        decimal_places = 0
    
    # Форматируем price с тем же количеством знаков и убираем нули в конце
    formatted = f"{price:.{decimal_places}f}".rstrip('0').rstrip('.')
    return formatted

# Создаем отдельные логгеры для каждого таймфрейма
def setup_timeframe_loggers():
    """Настройка отдельных логгеров для каждого таймфрейма"""
    # Создаем директорию для логов если не существует
    os.makedirs('logs', exist_ok=True)
    
    timeframes = ['1D', '12H', '4H', '1H', 'RANGE']
    loggers = {}
    
    for tf in timeframes:
        logger = logging.getLogger(f'TF_{tf}')
        logger.setLevel(logging.INFO)
        
        # Создаем handler для записи в отдельный файл
        handler = logging.FileHandler(
            f'logs/timeframe_{tf.lower()}_analysis.log',
            mode='a',
            encoding='utf-8'
        )
        handler.setFormatter(
            logging.Formatter('%(asctime)s | %(message)s', datefmt='%d.%m.%Y %H:%M:%S')
        )
        logger.addHandler(handler)
        loggers[tf] = logger
    
    return loggers


def analyze_symbol_multitimeframe(symbol, tracker, tf_loggers):
    """
    Многотаймфреймовый анализ одного символа
    Возвращает True если нужно продолжить работу с символом
    """
    # Инициализируем хранилище состояния
    if symbol not in tracker.last_analysis:
        tracker.last_analysis[symbol] = {}
    
    # === 1D АНАЛИЗ (каждые 12 часов) ===
    if tracker.should_analyze(symbol, '1D'):
        df_D = bybit_client.get_klines(symbol, interval='D')
        one_d_result = analyze_1d_ma_macd_volume(df_D, symbol)
        
        if one_d_result:
            print(f"[1D] {symbol}\n{one_d_result.get('summary', '')}")
            tf_loggers['1D'].info(f"{symbol} | {one_d_result.get('summary', 'N/A')}")
            
            # Определяем тренд
            ema_result = one_d_result.get("ema_result")
            volume_result = one_d_result.get("volume_result")
            ema_verdict = ema_result.get('trading_verdict') if ema_result else None
            volume_action = volume_result.get('action') if volume_result else None
            macd_action = one_d_result.get("macd_action")
            
            # BULLISH тренд: строгие требования для надежности
            # Вариант 1: Идеальный - цена выше MA200 + золотой крест + MACD + объем
            strong_buy = (
                ema_verdict == "STRONG_BUY" and
                macd_action == "BUY" and
                volume_action in ["HIGH_VOLUME", "NORMAL_VOLUME"]  # Достаточная активность
            )
            
            # Вариант 2: Допустимый - цена выше MA200 (без креста), но MACD сильно подтверждает
            cautious_buy_with_macd = (
                ema_verdict == "CAUTIOUS_BUY" and
                macd_action == "BUY" and
                volume_action in ["HIGH_VOLUME", "NORMAL_VOLUME"]  # Достаточная активность
            )
            
            all_buy = strong_buy or cautious_buy_with_macd
            
            # BEARISH тренд: аналогичная логика
            strong_sell = (
                ema_verdict == "STRONG_SELL" and
                macd_action == "SELL" and
                volume_action in ["HIGH_VOLUME", "NORMAL_VOLUME"]  # Достаточная активность
            )
            
            cautious_sell_with_macd = (
                ema_verdict == "CAUTIOUS_SELL" and
                macd_action == "SELL" and
                volume_action in ["HIGH_VOLUME", "NORMAL_VOLUME"]  # Достаточная активность
            )
            
            all_sell = strong_sell or cautious_sell_with_macd
            
            if all_buy or all_sell:
                trend_1d = "BULLISH" if all_buy else "BEARISH"
                logging.info(f"[1D] {symbol} → {'🟢 ПОКУПАТЬ' if all_buy else '🔴 ПРОДАВАТЬ'} (trend: {trend_1d})")
                tracker.last_analysis[symbol]['trend_1d'] = trend_1d
            else:
                # Тренд не определен - очищаем все нижние таймфреймы
                tracker.last_analysis[symbol].pop('trend_1d', None)
                tracker.last_analysis[symbol].pop('twelve_h_result', None)
                tracker.last_analysis[symbol].pop('four_h_result', None)
                return False
    
    # Получаем сохраненный тренд 1D
    trend_1d = tracker.last_analysis.get(symbol, {}).get('trend_1d')
    if not trend_1d:
        return False
    
    # === 12H АНАЛИЗ (каждые 4 часа) ===
    if tracker.should_analyze(symbol, '12H'):
        df_12h = bybit_client.get_klines(symbol, interval='720')
        twelve_h_result = analyze_12h_correction_strategy(df_12h, trend_1d=trend_1d, symbol=symbol)
        
        if twelve_h_result:
            print(f"[12H] {symbol}\n{twelve_h_result.get('summary', '')}")
            twelve_h_action = twelve_h_result.get('action')
            logging.info(f"[12H] {symbol} → {twelve_h_action}")
            
            tf_loggers['12H'].info(
                f"{symbol} | Action: {twelve_h_action} | Trend: {trend_1d} | "
                f"{twelve_h_result.get('summary', 'N/A')}"
            )
            
            if twelve_h_action in ['GO', 'ATTENTION']:
                tracker.last_analysis[symbol]['twelve_h_result'] = twelve_h_result
            else:
                # 12H дал STOP - очищаем нижние таймфреймы
                tracker.last_analysis[symbol].pop('twelve_h_result', None)
                tracker.last_analysis[symbol].pop('four_h_result', None)
                return False
    
    # Получаем сохраненный результат 12H
    twelve_h_result = tracker.last_analysis.get(symbol, {}).get('twelve_h_result')
    if not twelve_h_result or twelve_h_result.get('action') not in ['GO', 'ATTENTION']:
        return False
    
    # === 4H АНАЛИЗ (каждые 2 часа) ===
    if tracker.should_analyze(symbol, '4H'):
        df_4h = bybit_client.get_klines(symbol, interval='240')
        four_h_result = analyze_4h_entry_strategy(df_4h, trend_1d=trend_1d, twelve_h_signal=twelve_h_result, symbol=symbol)
        
        if four_h_result:
            print(f"[4H] {symbol}\n{four_h_result.get('summary', '')}")
            four_h_action = four_h_result.get('action')
            logging.info(f"[4H] {symbol} → {four_h_action}")
            
            tf_loggers['4H'].info(
                f"{symbol} | Action: {four_h_action} | Trend: {trend_1d} | "
                f"Readiness: {four_h_result.get('readiness_score', 'N/A')} | "
                f"{four_h_result.get('summary', 'N/A')}"
            )
            
            if four_h_action in ['GO', 'ATTENTION']:
                tracker.last_analysis[symbol]['four_h_result'] = four_h_result
                
                # Отправляем 4H сигнал только для LONG сценария
                if trend_1d == 'BULLISH':
                    success = send_telegram_message(
                        f"{'✅' if four_h_action == 'GO' else '⚠️'} 4H {'ГОТОВНОСТЬ' if four_h_action == 'GO' else 'ОСТОРОЖНО'}!\n{symbol}\n{four_h_result.get('summary', '')}"
                    )
                    if not success:
                        send_emergency_alert('TELEGRAM', symbol=symbol, details='4H signal failed')
            else:
                # 4H дал STOP - очищаем его из кэша
                tracker.last_analysis[symbol].pop('four_h_result', None)
                return False
    
    # Получаем сохраненный результат 4H
    four_h_result = tracker.last_analysis.get(symbol, {}).get('four_h_result')
    if not four_h_result or four_h_result.get('action') not in ['GO', 'ATTENTION']:
        return False
    
    # === 1H АНАЛИЗ (каждые 15 минут) ===
    if tracker.should_analyze(symbol, '1H'):
        df_1h = bybit_client.get_klines(symbol, interval='60')
        one_h_result = analyze_1h_execution(df_1h, four_h_signal=four_h_result, trend_1d=trend_1d, symbol=symbol)
        
        if one_h_result:
            print(f"[1H] {symbol}\n{one_h_result.get('summary', '')}")
            one_h_action = one_h_result.get('action')
            logging.info(f"[1H] {symbol} → {one_h_action}")
            
            # Получаем цены
            entry_price = one_h_result.get('entry_price', 0)
            stop_loss = one_h_result.get('stop_loss', 0)
            take_profit = one_h_result.get('take_profit', 0)
            risk_percent = one_h_result.get('risk_percent', 0)
            entry_score = one_h_result.get('entry_score', 0)
            
            # Форматируем SL и TP согласно entry_price (entry_price оставляем как есть)
            sl_str = format_price(stop_loss, entry_price)
            tp_str = format_price(take_profit, entry_price)
            
            tf_loggers['1H'].info(
                f"{symbol} | Action: {one_h_action} | Trend: {trend_1d} | "
                f"Score: {entry_score} | Entry: {entry_price} | "
                f"SL: {sl_str} | TP: {tp_str} | "
                f"Risk: {risk_percent:.2f}% | {one_h_result.get('summary', 'N/A')}"
            )
            
            # Отправляем 1H сигналы
            if one_h_action == 'ENTER' and trend_1d == 'BULLISH':
                success = send_telegram_message(
                    f"🎯 1H ВХОД В СДЕЛКУ!\n"
                    f"{symbol}\n"
                    f"Направление: {'LONG' if trend_1d == 'BULLISH' else 'SHORT'}\n"
                    f"Вход: {entry_price}\n"
                    f"Стоп: {sl_str}\n"
                    f"Тейк: {tp_str}\n"
                    f"Риск: {risk_percent:.2f}%\n"
                    f"R:R = 1:2\n\n"
                    f"{one_h_result.get('summary', '')}"
                )
                if not success:
                    send_emergency_alert('CRITICAL', symbol=symbol, details=f'ENTER {trend_1d} @ {entry_price}')
            
            elif one_h_action == 'WAIT_BETTER' and trend_1d == 'BULLISH':
                success = send_telegram_message(
                    f"🟡 1H ЖДАТЬ ЛУЧШЕЙ ЦЕНЫ!\n{symbol}\n{one_h_result.get('summary', '')}"
                )
                if not success:
                    send_emergency_alert('TELEGRAM', symbol=symbol, details='WAIT signal failed')
    
    return True


def analyze_symbol_range_trading(symbol, tracker, tf_loggers):
    """
    Range Trading анализ (работает параллельно с основной стратегией)
    """
    if not tracker.should_analyze(symbol, 'RANGE'):
        return
    
    df_1h_range = bybit_client.get_klines(symbol, interval='60')
    range_result = analyze_range_trading_signal(df_1h_range, symbol)
    
    if range_result and range_result['action'] in ['BUY', 'SELL']:
        entry_price = range_result['entry_price']
        stop_loss = range_result['stop_loss']
        take_profit = range_result['take_profit']
        risk_reward_ratio = range_result['risk_reward_ratio']
        confidence = range_result['confidence']
        
        # Форматируем SL и TP согласно entry_price (entry_price оставляем как есть)
        sl_str = format_price(stop_loss, entry_price)
        tp_str = format_price(take_profit, entry_price)
        
        # Логируем результат
        tf_loggers['RANGE'].info(
            f"{symbol} | Action: {range_result['action']} | "
            f"Confidence: {confidence}/10 | "
            f"Entry: {entry_price} | "
            f"SL: {sl_str} | "
            f"TP: {tp_str} | "
            f"R:R = 1:{risk_reward_ratio:.2f} | "
            f"{range_result['summary']}"
        )
        
        # Отправляем сигнал если уверенность >= 9 и R:R >= 1.5
        if (range_result['action'] == 'BUY' and
            confidence >= 9 and 
            risk_reward_ratio >= 7 and
            tracker.should_send_signal(symbol, range_result['action'], 'RANGE')):
            
            success = send_telegram_message(
                f"📊 RANGE TRADING SIGNAL (1H)!\n"
                f"{symbol}\n"
                f"{'🟢 LONG' if range_result['action'] == 'BUY' else '🔴 SHORT'}\n"
                f"Уверенность: {confidence}/10\n\n"
                f"Вход: {entry_price}\n"
                f"Стоп: {sl_str}\n"
                f"Тейк: {tp_str}\n"
                f"R:R = 1:{risk_reward_ratio:.2f}\n\n"
                f"Сигналы:\n" + "\n".join(range_result['signals'][:5])
            )
            
            if not success:
                send_emergency_alert('TELEGRAM', symbol=symbol, details='Range Trading signal failed')


def load_dynamic_symbols():
    """Загружает список символов из файла"""
    with open("data/filtered_symbols.txt", "r", encoding="utf-8") as f:
        symbols = [line.strip() for line in f if line.strip()]
    return list(dict.fromkeys(symbols))


def telegram_command_listener():
    """
    Отдельный поток для обработки Telegram команд
    """
    print("🤖 Telegram command listener запущен")
    logging.info("🤖 Telegram command listener запущен")
    
    while True:
        try:
            process_telegram_updates()
        except Exception:
            pass
        time.sleep(2)


def main():
    tracker = TimeframeAnalysisTracker()
    tf_loggers = setup_timeframe_loggers()
    
    CYCLE_PAUSE = 60
    
    logging.info("="*60)
    logging.info("🚀 Бот запущен. Начало работы.")
    logging.info("="*60)
    
    telegram_thread = threading.Thread(target=telegram_command_listener, daemon=True)
    telegram_thread.start()

    while True:
        cycle_start = time.time()
        symbols = load_dynamic_symbols()
        
        for symbol in symbols:
            try:
                analyze_symbol_range_trading(symbol, tracker, tf_loggers)
                analyze_symbol_multitimeframe(symbol, tracker, tf_loggers)
            except Exception as e:
                error_msg = f"❌ Ошибка анализа {symbol}: {e}"
                print(error_msg)
                logging.error(error_msg)
                
                # Отправляем аварийное уведомление о критической ошибке
                send_emergency_alert('ANALYSIS', symbol=symbol, details=str(e))
                continue
        
        cycle_duration = time.time() - cycle_start
        print(f"\n⏱️  Цикл завершен за {cycle_duration:.1f}s. Пауза {CYCLE_PAUSE}s...\n")
        time.sleep(CYCLE_PAUSE)

if __name__ == "__main__":
    # answer = bybit_client.get_wallet_balance()
    # print(answer)
    main()
    # result = bybit_client.place_order(
    #     symbol="ENAUSDT",
    #     side="Buy",
    #     orderType="Limit",
    #     qty="2",
    #     price="0.2500",
    #     timeInForce="PostOnly",
    #     orderLinkId="my order 012543"
    # )   
    # print(result)