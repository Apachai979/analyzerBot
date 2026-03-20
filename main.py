import threading
import time
import os
import logging
import pandas as pd

from analyzes.entry_trigger_1h import EntryTrigger1hConfig, entry_trigger_1h
from analyzes.setup_filter_4h import SetupFilter4hConfig, setup_filter_4h
from analyzes.trend_filter_12h_v2 import TrendFilter12hConfig, trend_filter_12h
from bybit_client_v2 import bybit_client
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


def prepare_ohlcv_for_filter(raw_df, interval_minutes, drop_incomplete_last_candle=True):
    """Подготавливает OHLCV для фильтров: типы, индекс времени, сортировка, удаление незакрытой свечи."""
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    df = raw_df.copy()
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.set_index("timestamp")
    df = df[["open", "high", "low", "close", "volume"]]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.dropna()

    if df.empty:
        return df

    if drop_incomplete_last_candle:
        now_utc = pd.Timestamp.now(tz="UTC")
        interval_delta = pd.Timedelta(minutes=interval_minutes)
        interval_ns = interval_delta.value
        current_bucket_start = pd.Timestamp(
            (now_utc.value // interval_ns) * interval_ns,
            tz="UTC",
        )
        if df.index[-1] >= current_bucket_start:
            df = df.iloc[:-1]

    return df


def derive_filter_action(passed, hard_passed, soft_score, required_score):
    """Преобразует результат фильтра в GO/ATTENTION/STOP для логов и Telegram."""
    if passed:
        return "GO"
    if hard_passed and soft_score >= max(1, required_score - 1):
        return "ATTENTION"
    return "STOP"


def format_12h_summary(result):
    """Короткий summary для 12H bias-filter."""
    required_score = result.details.get("soft_score_required", result.soft_score_max)
    status = "GO" if result.passed else ("ATTENTION" if result.hard_passed else "STOP")
    return (
        f"12H BIAS: {status}\n"
        f"Hard: {'OK' if result.hard_passed else 'FAIL'} | Soft: {result.soft_score}/{result.soft_score_max} (need {required_score})\n"
        f"Reason: {result.reason}"
    )


def format_4h_summary(result):
    """Короткий human-readable summary для 4H setup-filter."""
    required_score = result.details.get("soft_score_required", result.soft_score_max)
    obv = result.details.get("obv", {})
    obv_score = sum(
        int(obv.get(key, False))
        for key in ["obv_bullish_state", "obv_strength_supportive", "obv_bullish_divergence"]
    )
    soft = result.details.get("soft_conditions", {})
    return (
        f"4H SETUP: {result.setup_state}\n"
        f"Hard: {'OK' if result.hard_passed else 'FAIL'} | Soft: {result.soft_score}/{result.soft_score_max} (need {required_score})\n"
        f"Pullback: {'YES' if soft.get('touched_working_zone') else 'NO'} | Reclaim EMA20: {'YES' if soft.get('reclaimed_ema20') else 'NO'} | OBV: {obv_score}/3\n"
        f"Reason: {result.reason}"
    )


def format_1h_summary(result):
    """Короткий human-readable summary для 1H trigger."""
    required_score = result.details.get("soft_score_required", result.soft_score_max)
    lines = [
        f"1H TRIGGER: {result.action}",
        f"State: {result.trigger_state}",
        f"Hard: {'OK' if result.hard_passed else 'FAIL'} | Soft: {result.soft_score}/{result.soft_score_max} (need {required_score})",
    ]
    if result.entry_price is not None:
        lines.append(
            f"Entry: {result.entry_price} | SL: {result.stop_loss} | TP: {result.take_profit} | RR: {result.reward_risk:.2f}"
        )
    lines.append(f"Reason: {result.reason}")
    return "\n".join(lines)

# Создаем отдельные логгеры для каждого таймфрейма
def setup_timeframe_loggers():
    """Настройка отдельных логгеров для каждого таймфрейма"""
    # Создаем директорию для логов если не существует
    os.makedirs('logs', exist_ok=True)
    
    timeframes = ['12H', '4H', '1H', 'RANGE']
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
    
    # === 12H АНАЛИЗ (каждые 4 часа) ===
    if tracker.should_analyze(symbol, '12H'):
        raw_12h = bybit_client.get_klines(symbol, interval='720')
        df_12h = prepare_ohlcv_for_filter(raw_12h, interval_minutes=720, drop_incomplete_last_candle=True)

        if df_12h.empty:
            tracker.last_analysis[symbol].pop('twelve_h_result', None)
            tracker.last_analysis[symbol].pop('four_h_result', None)
            return False

        twelve_h_result = trend_filter_12h(
            df_12h,
            config=TrendFilter12hConfig(
                min_required_rows=260,
                min_soft_conditions_passed=2,
            ),
        )
        twelve_h_action = derive_filter_action(
            passed=twelve_h_result.passed,
            hard_passed=twelve_h_result.hard_passed,
            soft_score=twelve_h_result.soft_score,
            required_score=twelve_h_result.details.get('soft_score_required', twelve_h_result.soft_score_max),
        )
        twelve_h_summary = format_12h_summary(twelve_h_result)

        print(f"[12H] {symbol}\n{twelve_h_summary}")
        logging.info(f"[12H] {symbol} → {twelve_h_action}")

        tf_loggers['12H'].info(
            f"{symbol} | Action: {twelve_h_action} | {twelve_h_summary.replace(chr(10), ' | ')}"
        )

        if twelve_h_action in ['GO', 'ATTENTION']:
            tracker.last_analysis[symbol]['twelve_h_result'] = {
                'action': twelve_h_action,
                'summary': twelve_h_summary,
                'result': twelve_h_result,
            }
        else:
            tracker.last_analysis[symbol].pop('twelve_h_result', None)
            tracker.last_analysis[symbol].pop('four_h_result', None)
            return False
    
    # Получаем сохраненный результат 12H
    twelve_h_result = tracker.last_analysis.get(symbol, {}).get('twelve_h_result')
    if not twelve_h_result or twelve_h_result.get('action') not in ['GO', 'ATTENTION']:
        return False
    
    # === 4H АНАЛИЗ (каждые 2 часа) ===
    if tracker.should_analyze(symbol, '4H'):
        raw_4h = bybit_client.get_klines(symbol, interval='240')
        df_4h = prepare_ohlcv_for_filter(raw_4h, interval_minutes=240, drop_incomplete_last_candle=True)

        if df_4h.empty:
            tracker.last_analysis[symbol].pop('four_h_result', None)
            return False

        four_h_result = setup_filter_4h(
            df_4h,
            trend_bias_passed=twelve_h_result['result'].passed,
            trend_bias_reason=twelve_h_result['result'].reason,
            config=SetupFilter4hConfig(
                min_required_rows=220,
                min_soft_conditions_passed=6,
            ),
        )
        four_h_action = derive_filter_action(
            passed=four_h_result.passed,
            hard_passed=four_h_result.hard_passed,
            soft_score=four_h_result.soft_score,
            required_score=four_h_result.details.get('soft_score_required', four_h_result.soft_score_max),
        )
        four_h_summary = format_4h_summary(four_h_result)

        print(f"[4H] {symbol}\n{four_h_summary}")
        logging.info(f"[4H] {symbol} → {four_h_action}")

        tf_loggers['4H'].info(
            f"{symbol} | Action: {four_h_action} | {four_h_summary.replace(chr(10), ' | ')}"
        )

        if four_h_action in ['GO', 'ATTENTION']:
            tracker.last_analysis[symbol]['four_h_result'] = {
                'action': four_h_action,
                'summary': four_h_summary,
                'result': four_h_result,
            }

            success = send_telegram_message(
                f"{'✅' if four_h_action == 'GO' else '⚠️'} 4H {'ГОТОВНОСТЬ' if four_h_action == 'GO' else 'ОСТОРОЖНО'}\n"
                f"{symbol}\n{four_h_summary}"
            )
            if not success:
                send_emergency_alert('TELEGRAM', symbol=symbol, details='4H setup signal failed')
        else:
            tracker.last_analysis[symbol].pop('four_h_result', None)
            return False
    
    # Получаем сохраненный результат 4H
    four_h_result = tracker.last_analysis.get(symbol, {}).get('four_h_result')
    if not four_h_result or four_h_result.get('action') not in ['GO', 'ATTENTION']:
        return False
    
    # === 1H АНАЛИЗ (каждые 15 минут) ===
    if tracker.should_analyze(symbol, '1H'):
        raw_1h = bybit_client.get_klines(symbol, interval='60')
        df_1h = prepare_ohlcv_for_filter(raw_1h, interval_minutes=60, drop_incomplete_last_candle=True)

        if df_1h.empty:
            return False

        one_h_result = entry_trigger_1h(
            df_1h,
            setup_result=four_h_result['result'],
            config=EntryTrigger1hConfig(
                min_required_rows=180,
                min_soft_conditions_passed=5,
            ),
        )

        one_h_summary = format_1h_summary(one_h_result)
        print(f"[1H] {symbol}\n{one_h_summary}")
        logging.info(f"[1H] {symbol} → {one_h_result.action}")

        entry_price = one_h_result.entry_price
        stop_loss = one_h_result.stop_loss
        take_profit = one_h_result.take_profit
        risk_percent = one_h_result.risk_percent

        sl_str = format_price(stop_loss, entry_price) if entry_price and stop_loss is not None else str(stop_loss)
        tp_str = format_price(take_profit, entry_price) if entry_price and take_profit is not None else str(take_profit)

        tf_loggers['1H'].info(
            f"{symbol} | Action: {one_h_result.action} | {one_h_summary.replace(chr(10), ' | ')}"
        )

        if one_h_result.action == 'ENTER':
            success = send_telegram_message(
                f"🎯 1H ВХОД В СДЕЛКУ!\n"
                f"{symbol}\n"
                f"Направление: LONG\n"
                f"Вход: {entry_price}\n"
                f"Стоп: {sl_str}\n"
                f"Тейк: {tp_str}\n"
                f"Риск: {risk_percent:.2f}%\n"
                f"R:R = {one_h_result.reward_risk:.2f}\n\n"
                f"{one_h_summary}"
            )
            if not success:
                send_emergency_alert('CRITICAL', symbol=symbol, details=f'ENTER LONG @ {entry_price}')

        elif one_h_result.action == 'WAIT_BETTER':
            success = send_telegram_message(
                f"🟡 1H ЖДАТЬ ЛУЧШЕЙ ЦЕНЫ\n{symbol}\n{one_h_summary}"
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
    source_files = ["data/dynamic_symbols.txt", "data/filtered_symbols.txt"]
    symbols: list[str] = []
    for file_path in source_files:
        if not os.path.exists(file_path):
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            symbols = [line.strip() for line in f if line.strip()]
        if symbols:
            break
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