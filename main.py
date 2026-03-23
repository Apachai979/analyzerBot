import threading
import time
import os
import logging

from calibration_report_v3 import run_scheduled_calibration
from config import (
    CALIBRATION_CHECK_PAUSE_SECONDS,
    CALIBRATION_HEARTBEAT_INTERVAL_SECONDS,
    MAIN_LOOP_PAUSE_SECONDS,
)
from telegram_utils import send_telegram_message, process_telegram_updates, send_emergency_alert
from strategies.base import StrategyContext
from strategies.registry import build_default_strategies
from strategies.runner import StrategyRunner
from symbol_universe import load_common_symbols
from time_frame_tracker import TimeframeAnalysisTracker
from trade_monitor import load_active_trades, monitor_active_trades
from bybit_client_v2 import bybit_client

# Настройка логирования
logging.basicConfig(
    filename='analyzer.log',
    filemode='a',
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    encoding='utf-8'
)

CALIBRATION_LOCK = threading.Lock()

# Создаем отдельные логгеры для каждого таймфрейма
def setup_timeframe_loggers():
    """Настройка отдельных логгеров для каждого таймфрейма"""
    # Создаем директорию для логов если не существует
    os.makedirs('logs', exist_ok=True)
    
    timeframes = ['12H', '4H', '1H', 'RANGE', 'MONITOR']
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


def setup_calibration_logger():
    """Создает отдельный логгер для background calibration worker и его heartbeat."""
    os.makedirs('logs', exist_ok=True)

    logger = logging.getLogger('CALIBRATION_WORKER')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(
            'logs/calibration_scheduler.log',
            mode='a',
            encoding='utf-8',
        )
        handler.setFormatter(
            logging.Formatter('%(asctime)s | %(message)s', datefmt='%d.%m.%Y %H:%M:%S')
        )
        logger.addHandler(handler)

    return logger


def load_strategy_symbols():
    """Загружает общий список символов для всех стратегий."""
    with CALIBRATION_LOCK:
        return load_common_symbols()


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


def run_scheduled_calibration_sync():
    """Запускает встроенный scheduler calibration_report_v3 и пишет результат в логи."""
    with CALIBRATION_LOCK:
        result = run_scheduled_calibration()
    if not result.get('ran'):
        return result

    message = (
        "[CALIBRATION] scheduled refresh completed | "
        f"refreshed_filtered={result.get('refreshed_filtered')} | "
        f"updated_dynamic={result.get('updated_dynamic')} | "
        f"symbols={result.get('symbols_count')} | "
        f"dynamic_symbols={result.get('dynamic_symbols_count')}"
    )
    print(message)
    logging.info(message)
    return result


def calibration_scheduler_worker(calibration_logger, pause_seconds=60, heartbeat_interval_seconds=300):
    """Фоновый поток для периодической проверки встроенного calibration scheduler."""
    logging.info(f"[CALIBRATION] background worker started | pause={pause_seconds}s")
    calibration_logger.info(
        f"worker_started | check_pause={pause_seconds}s | heartbeat_interval={heartbeat_interval_seconds}s"
    )
    last_heartbeat_at = 0.0
    last_completed_run_at = 0.0
    last_reason = 'init'

    def format_heartbeat_timestamp(timestamp_seconds):
        if not timestamp_seconds:
            return 'never'
        return time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(timestamp_seconds))

    while True:
        try:
            result = run_scheduled_calibration_sync()
            last_reason = result.get('reason', 'unknown') if isinstance(result, dict) else 'unknown'

            if result.get('ran'):
                calibration_logger.info(
                    "scheduled_run_completed | "
                    f"reason={result.get('reason')} | "
                    f"refreshed_filtered={result.get('refreshed_filtered')} | "
                    f"updated_dynamic={result.get('updated_dynamic')} | "
                    f"symbols={result.get('symbols_count')} | "
                    f"dynamic_symbols={result.get('dynamic_symbols_count')}"
                )
                last_completed_run_at = time.time()

            now_ts = time.time()
            if now_ts - last_heartbeat_at >= heartbeat_interval_seconds:
                if now_ts - last_completed_run_at >= heartbeat_interval_seconds:
                    calibration_logger.info(
                        "heartbeat | "
                        f"worker_alive=true | "
                        f"last_reason={last_reason} | "
                        f"last_completed_run_at={format_heartbeat_timestamp(last_completed_run_at)} | "
                        f"next_check_in={pause_seconds}s"
                    )
                last_heartbeat_at = now_ts
        except Exception as error:
            error_msg = f"[CALIBRATION] background worker error: {error}"
            print(error_msg)
            logging.error(error_msg)
            calibration_logger.error(f"worker_error | error={error}")
            send_emergency_alert('CALIBRATION', details=str(error))

        time.sleep(pause_seconds)


def main():
    tracker = TimeframeAnalysisTracker()
    tracker.active_trades = load_active_trades()
    strategy_runner = StrategyRunner(build_default_strategies())
    tf_loggers = setup_timeframe_loggers()
    calibration_logger = setup_calibration_logger()
    
    CYCLE_PAUSE = MAIN_LOOP_PAUSE_SECONDS
    CALIBRATION_CHECK_PAUSE = CALIBRATION_CHECK_PAUSE_SECONDS
    
    logging.info("="*60)
    logging.info("🚀 Бот запущен. Начало работы.")
    logging.info("="*60)
    
    telegram_thread = threading.Thread(target=telegram_command_listener, daemon=True)
    telegram_thread.start()

    calibration_thread = threading.Thread(
        target=calibration_scheduler_worker,
        kwargs={
            'calibration_logger': calibration_logger,
            'pause_seconds': CALIBRATION_CHECK_PAUSE,
            'heartbeat_interval_seconds': CALIBRATION_HEARTBEAT_INTERVAL_SECONDS,
        },
        daemon=True,
    )
    calibration_thread.start()

    while True:
        cycle_start = time.time()
        monitor_active_trades(tracker.active_trades, tf_loggers)
        symbols = load_strategy_symbols()
        
        for symbol in symbols:
            try:
                strategy_runner.analyze_symbol(
                    StrategyContext(
                        symbol=symbol,
                        tracker=tracker,
                        tf_loggers=tf_loggers,
                        market_data_provider=bybit_client,
                    )
                )
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
    main()