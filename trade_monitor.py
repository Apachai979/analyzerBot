import json
import logging
import os

import pandas as pd

from bybit_client_v2 import bybit_client
from config import SPOT_POSITION_MIN_USD_VALUE
from telegram_utils import send_emergency_alert, send_telegram_message


ACTIVE_TRADES_FILE = 'data/active_trades.json'


def utc_now_iso():
    """Возвращает текущий UTC timestamp в ISO-формате."""
    return pd.Timestamp.now(tz='UTC').isoformat()


def format_price(price, reference_price):
    """Форматирует цену в соответствии с количеством знаков после запятой в reference_price."""
    if price is None or reference_price is None:
        return str(price)

    ref_str = f"{reference_price:.15f}".rstrip('0').rstrip('.')
    if '.' in ref_str:
        decimal_places = len(ref_str.split('.')[1])
    else:
        decimal_places = 0

    return f"{price:.{decimal_places}f}".rstrip('0').rstrip('.')


def load_active_trades(file_path=ACTIVE_TRADES_FILE):
    """Загружает активные сделки из JSON-файла."""
    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, 'r', encoding='utf-8') as file_handle:
            payload = json.load(file_handle)
    except (OSError, json.JSONDecodeError) as error:
        logging.error(f"Не удалось загрузить active trades: {error}")
        return {}

    trades = payload.get('trades', payload)
    return trades if isinstance(trades, dict) else {}


def save_active_trades(active_trades, file_path=ACTIVE_TRADES_FILE):
    """Сохраняет состояние активных сделок в JSON-файл."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    payload = {
        'updated_at': utc_now_iso(),
        'trades': active_trades,
    }
    with open(file_path, 'w', encoding='utf-8') as file_handle:
        json.dump(payload, file_handle, ensure_ascii=False, indent=2)


def calculate_trade_pnl_percent(direction, entry_price, current_price):
    """Считает текущий PnL сделки в процентах."""
    if entry_price in (None, 0) or current_price is None:
        return None

    if direction == 'SHORT':
        return (entry_price - current_price) / entry_price * 100
    return (current_price - entry_price) / entry_price * 100


def safe_float(value, default=0.0):
    """Преобразует значение в float, возвращая default при ошибке."""
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def get_base_coin(symbol):
    """Возвращает базовую монету для стандартной spot-пары к USDT."""
    normalized_symbol = str(symbol or '').upper()
    if normalized_symbol.endswith('USDT') and len(normalized_symbol) > 4:
        return normalized_symbol[:-4]
    return None


def resolve_trade_exit_reason(direction, current_price, stop_loss, take_profit):
    """Проверяет, достигла ли сделка стопа или тейка по текущей цене."""
    if current_price is None:
        return None

    if direction == 'SHORT':
        if take_profit is not None and current_price <= take_profit:
            return 'TAKE_PROFIT_HIT'
        if stop_loss is not None and current_price >= stop_loss:
            return 'STOP_LOSS_HIT'
        return None

    if take_profit is not None and current_price >= take_profit:
        return 'TAKE_PROFIT_HIT'
    if stop_loss is not None and current_price <= stop_loss:
        return 'STOP_LOSS_HIT'
    return None


def register_active_trade(
    active_trades,
    *,
    symbol,
    strategy,
    direction,
    entry_price,
    stop_loss,
    take_profit,
    risk_percent=None,
    reward_risk=None,
    note=None,
):
    """Регистрирует новую активную сделку и не дублирует уже открытую по символу."""
    existing_trade = active_trades.get(symbol)
    if existing_trade and existing_trade.get('status') == 'OPEN':
        return False, existing_trade

    trade = {
        'symbol': symbol,
        'strategy': strategy,
        'direction': direction,
        'entry_price': entry_price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'risk_percent': risk_percent,
        'reward_risk': reward_risk,
        'note': note,
        'status': 'OPEN',
        'opened_at': utc_now_iso(),
        'closed_at': None,
        'close_reason': None,
        'close_price': None,
        'last_price': entry_price,
        'last_checked_at': None,
        'current_pnl_percent': 0.0,
        'max_favorable_pnl_percent': 0.0,
    }
    active_trades[symbol] = trade
    save_active_trades(active_trades)
    return True, trade


def format_monitor_status_line(trade, current_price, pnl_percent):
    """Формирует компактную строку статуса для логов мониторинга."""
    current_price_str = format_price(current_price, trade.get('entry_price')) if current_price is not None else 'None'
    stop_str = format_price(trade.get('stop_loss'), trade.get('entry_price')) if trade.get('stop_loss') is not None else 'None'
    take_str = format_price(trade.get('take_profit'), trade.get('entry_price')) if trade.get('take_profit') is not None else 'None'
    pnl_str = f"{pnl_percent:.2f}%" if pnl_percent is not None else 'None'
    exchange_state = trade.get('exchange_state', 'UNKNOWN')
    exchange_source = trade.get('exchange_sync_source', 'unknown')
    asset_qty = trade.get('exchange_asset_qty')
    asset_qty_str = f"{asset_qty:.8f}" if isinstance(asset_qty, (int, float)) else 'None'
    return (
        f"{trade['symbol']} | {trade['strategy']} | {trade['direction']} | status={trade['status']} | "
        f"exchange={exchange_state}({exchange_source}) | asset_qty={asset_qty_str} | entry={trade['entry_price']} | current={current_price_str} | "
        f"stop={stop_str} | take={take_str} | pnl={pnl_str}"
    )


def notify_exchange_trade_open(trade, tf_loggers):
    """Отправляет уведомление, когда биржа подтвердила открытие сделки."""
    current_price = trade.get('last_price') or trade.get('entry_price')
    pnl_percent = trade.get('current_pnl_percent')
    current_price_str = format_price(current_price, trade.get('entry_price')) if current_price is not None else 'None'
    stop_str = format_price(trade.get('stop_loss'), trade.get('entry_price')) if trade.get('stop_loss') is not None else 'None'
    take_str = format_price(trade.get('take_profit'), trade.get('entry_price')) if trade.get('take_profit') is not None else 'None'
    pnl_display = f"{pnl_percent:.2f}%" if pnl_percent is not None else 'N/A'

    message = (
        f"✅ СДЕЛКА ПОДТВЕРЖДЕНА БИРЖЕЙ\n"
        f"{trade.get('symbol')}\n"
        f"Стратегия: {trade.get('strategy')}\n"
        f"Направление: {trade.get('direction')}\n"
        f"Источник: {trade.get('exchange_sync_source')}\n"
        f"Вход: {trade.get('entry_price')}\n"
        f"Текущая цена: {current_price_str}\n"
        f"Стоп: {stop_str}\n"
        f"Тейк: {take_str}\n"
        f"PnL: {pnl_display}"
    )
    tf_loggers['MONITOR'].info(
        f"{trade.get('symbol')} | EXCHANGE_OPEN_CONFIRMED | source={trade.get('exchange_sync_source')}"
    )

    if not send_telegram_message(message):
        send_emergency_alert(
            'TELEGRAM',
            symbol=trade.get('symbol'),
            details='exchange open confirmation notification failed',
        )


def notify_exchange_trade_pending(trade, tf_loggers):
    """Отправляет уведомление, когда биржа увидела активный ордер, но позиция еще не открыта."""
    current_price = trade.get('last_price') or trade.get('entry_price')
    current_price_str = format_price(current_price, trade.get('entry_price')) if current_price is not None else 'None'
    stop_str = format_price(trade.get('stop_loss'), trade.get('entry_price')) if trade.get('stop_loss') is not None else 'None'
    take_str = format_price(trade.get('take_profit'), trade.get('entry_price')) if trade.get('take_profit') is not None else 'None'

    message = (
        f"🟡 ОРДЕР ПОДТВЕРЖДЕН БИРЖЕЙ\n"
        f"{trade.get('symbol')}\n"
        f"Стратегия: {trade.get('strategy')}\n"
        f"Направление: {trade.get('direction')}\n"
        f"Источник: {trade.get('exchange_sync_source')}\n"
        f"Статус: PENDING\n"
        f"Вход: {trade.get('entry_price')}\n"
        f"Текущая цена: {current_price_str}\n"
        f"Стоп: {stop_str}\n"
        f"Тейк: {take_str}"
    )
    tf_loggers['MONITOR'].info(
        f"{trade.get('symbol')} | EXCHANGE_PENDING_CONFIRMED | source={trade.get('exchange_sync_source')}"
    )

    if not send_telegram_message(message):
        send_emergency_alert(
            'TELEGRAM',
            symbol=trade.get('symbol'),
            details='exchange pending confirmation notification failed',
        )


def should_use_spot_wallet_sync(trade):
    """Определяет, нужно ли подтверждать сделку через баланс спотовой монеты."""
    return trade.get('direction') == 'LONG' and get_base_coin(trade.get('symbol')) is not None


def sync_spot_wallet_state(trade, current_price):
    """Синхронизирует spot long-сделку через баланс базовой монеты в unified wallet."""
    symbol = trade.get('symbol')
    base_coin = get_base_coin(symbol)
    if not base_coin:
        return None

    previous_exchange_state = trade.get('exchange_state')
    wallet_state = bybit_client.get_wallet_balance(accountType='UNIFIED', coin=base_coin)
    trade['exchange_synced_at'] = utc_now_iso()
    trade['exchange_sync_source'] = 'spot_wallet'
    trade['exchange_previous_state'] = previous_exchange_state

    if not wallet_state:
        trade['exchange_state'] = 'SYNC_ERROR'
        return None

    coin_data = wallet_state.get('coin') or {}
    account_data = wallet_state.get('account') or {}
    wallet_balance = safe_float(coin_data.get('walletBalance'))
    equity = safe_float(coin_data.get('equity'))
    free_balance = safe_float(coin_data.get('availableToWithdraw'))
    asset_qty = max(wallet_balance, equity)
    asset_value_usdt = asset_qty * current_price if current_price is not None else None
    has_spot_asset = asset_qty > 0 and (
        asset_value_usdt is None or asset_value_usdt >= SPOT_POSITION_MIN_USD_VALUE
    )

    open_orders = bybit_client.get_open_orders(symbol=symbol, category='spot', limit=50) or []
    active_orders = [
        order
        for order in open_orders
        if str(order.get('symbol', '')).upper() == str(symbol).upper()
    ]

    if has_spot_asset:
        state = 'OPEN'
    elif active_orders:
        state = 'PENDING'
    else:
        state = 'FLAT'

    trade['exchange_state'] = state
    trade['exchange_has_position'] = has_spot_asset
    trade['exchange_position_side'] = 'Buy' if has_spot_asset else None
    trade['exchange_position_size'] = asset_qty
    trade['exchange_asset_coin'] = base_coin
    trade['exchange_asset_qty'] = asset_qty
    trade['exchange_asset_free_qty'] = free_balance
    trade['exchange_asset_value_usdt'] = asset_value_usdt
    trade['exchange_account_type'] = account_data.get('accountType')
    trade['exchange_open_orders_count'] = len(active_orders)

    if state in {'OPEN', 'PENDING'}:
        trade['exchange_seen_open'] = True

    return {
        'symbol': symbol,
        'state': state,
        'has_position': has_spot_asset,
        'position_size': asset_qty,
        'position_side': 'Buy' if has_spot_asset else None,
        'position': coin_data,
        'open_orders': active_orders,
        'asset_coin': base_coin,
        'asset_qty': asset_qty,
        'asset_value_usdt': asset_value_usdt,
    }


def sync_trade_with_exchange(trade, current_price):
    """Синхронизирует локальную сделку с биржей и обновляет exchange-поля best-effort."""
    symbol = trade.get('symbol')
    if not symbol:
        return None

    if should_use_spot_wallet_sync(trade):
        return sync_spot_wallet_state(trade, current_price)

    sync_state = bybit_client.sync_position_state(symbol)
    trade['exchange_synced_at'] = utc_now_iso()
    trade['exchange_sync_source'] = 'positions'
    trade['exchange_previous_state'] = trade.get('exchange_state')

    if not sync_state:
        trade['exchange_state'] = 'SYNC_ERROR'
        return None

    trade['exchange_state'] = sync_state.get('state')
    trade['exchange_has_position'] = sync_state.get('has_position')
    trade['exchange_position_size'] = sync_state.get('position_size')
    trade['exchange_position_side'] = sync_state.get('position_side')
    trade['exchange_asset_qty'] = sync_state.get('position_size')

    if sync_state.get('state') in {'OPEN', 'PENDING'}:
        trade['exchange_seen_open'] = True

    return sync_state


def finalize_trade_close(trade, *, close_reason, current_price, pnl_percent, tf_loggers):
    """Закрывает локальную сделку, логирует событие и отправляет Telegram-уведомление."""
    trade['status'] = 'CLOSED'
    trade['closed_at'] = utc_now_iso()
    trade['close_reason'] = close_reason
    trade['close_price'] = current_price

    if close_reason == 'TAKE_PROFIT_HIT':
        close_label = 'тейк-профит'
    elif close_reason == 'STOP_LOSS_HIT':
        close_label = 'стоп-лосс'
    else:
        close_label = 'позиция закрыта на бирже'

    pnl_display = f"{pnl_percent:.2f}%" if pnl_percent is not None else 'N/A'
    message = (
        f"🔔 СДЕЛКА ЗАВЕРШЕНА\n"
        f"{trade.get('symbol')}\n"
        f"Стратегия: {trade.get('strategy')}\n"
        f"Направление: {trade.get('direction')}\n"
        f"Причина: {close_label}\n"
        f"Вход: {trade.get('entry_price')}\n"
        f"Выход: {current_price}\n"
        f"PnL: {pnl_display}"
    )
    print(f"[MONITOR] {trade.get('symbol')} → {close_reason}")
    logging.info(f"[MONITOR] {trade.get('symbol')} → {close_reason} | pnl={pnl_percent}")
    tf_loggers['MONITOR'].info(
        f"{trade.get('symbol')} | CLOSED | reason={close_reason} | price={current_price} | pnl={pnl_percent}"
    )

    if not send_telegram_message(message):
        send_emergency_alert(
            'TELEGRAM',
            symbol=trade.get('symbol'),
            details=f'trade monitor close notification failed: {close_reason}',
        )


def monitor_active_trades(active_trades, tf_loggers):
    """Постоянно отслеживает уже открытые сделки и закрывает их локальный статус по TP/SL."""
    open_symbols = [
        symbol
        for symbol, trade in active_trades.items()
        if trade.get('status') == 'OPEN'
    ]
    if not open_symbols:
        return

    prices = bybit_client.get_multiple_prices(open_symbols)
    now_iso = utc_now_iso()
    has_updates = False

    for symbol in open_symbols:
        trade = active_trades.get(symbol)
        if not trade:
            continue

        current_price = prices.get(symbol)

        sync_state = sync_trade_with_exchange(trade, current_price)
        previous_exchange_state = trade.get('exchange_previous_state')
        current_exchange_state = trade.get('exchange_state')

        if previous_exchange_state in {None, 'FLAT'} and current_exchange_state == 'PENDING':
            if not trade.get('exchange_pending_notified'):
                notify_exchange_trade_pending(trade, tf_loggers)
                trade['exchange_pending_notified'] = True
                has_updates = True

        if previous_exchange_state == 'PENDING' and current_exchange_state == 'OPEN':
            if not trade.get('exchange_open_notified'):
                notify_exchange_trade_open(trade, tf_loggers)
                trade['exchange_open_notified'] = True
                has_updates = True

        if sync_state and sync_state.get('state') == 'FLAT' and trade.get('exchange_seen_open'):
            finalize_trade_close(
                trade,
                close_reason='EXCHANGE_POSITION_CLOSED',
                current_price=trade.get('last_price') or trade.get('entry_price'),
                pnl_percent=trade.get('current_pnl_percent'),
                tf_loggers=tf_loggers,
            )
            has_updates = True
            continue

        if current_price is None:
            tf_loggers['MONITOR'].warning(f"{symbol} | price unavailable during active trade monitoring")
            continue

        pnl_percent = calculate_trade_pnl_percent(
            trade.get('direction'),
            trade.get('entry_price'),
            current_price,
        )
        trade['last_price'] = current_price
        trade['last_checked_at'] = now_iso
        trade['current_pnl_percent'] = pnl_percent

        previous_best = trade.get('max_favorable_pnl_percent')
        if pnl_percent is not None:
            if previous_best is None:
                trade['max_favorable_pnl_percent'] = pnl_percent
            else:
                trade['max_favorable_pnl_percent'] = max(previous_best, pnl_percent)

        tf_loggers['MONITOR'].info(format_monitor_status_line(trade, current_price, pnl_percent))
        has_updates = True

        close_reason = resolve_trade_exit_reason(
            trade.get('direction'),
            current_price,
            trade.get('stop_loss'),
            trade.get('take_profit'),
        )
        if not close_reason:
            continue
        finalize_trade_close(
            trade,
            close_reason=close_reason,
            current_price=current_price,
            pnl_percent=pnl_percent,
            tf_loggers=tf_loggers,
        )
        has_updates = True

    if has_updates:
        save_active_trades(active_trades)