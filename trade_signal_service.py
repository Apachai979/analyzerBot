import logging

from telegram_utils import send_emergency_alert, send_telegram_message
from trade_monitor import format_price, register_active_trade


def register_and_notify_trade(
    active_trades,
    tf_loggers,
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
    notification_message,
    duplicate_log_message,
    emergency_channel,
    emergency_details,
):
    """Регистрирует сделку в локальном реестре и отправляет уведомление только при новом входе."""
    registered, active_trade = register_active_trade(
        active_trades,
        symbol=symbol,
        strategy=strategy,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_percent=risk_percent,
        reward_risk=reward_risk,
        note=note,
    )
    if not registered:
        tf_loggers['MONITOR'].info(
            f"{symbol} | {duplicate_log_message} | existing_status={active_trade.get('status')}"
        )
        return False, active_trade

    success = send_telegram_message(notification_message)
    if not success:
        send_emergency_alert(emergency_channel, symbol=symbol, details=emergency_details)
    return True, active_trade


def handle_multitimeframe_entry_signal(active_trades, tf_loggers, *, symbol, entry_result, one_h_summary):
    """Обрабатывает сигнал входа по multi-timeframe стратегии."""
    entry_price = entry_result.entry_price
    stop_loss = entry_result.stop_loss
    take_profit = entry_result.take_profit
    risk_percent = entry_result.risk_percent

    sl_str = format_price(stop_loss, entry_price) if entry_price and stop_loss is not None else str(stop_loss)
    tp_str = format_price(take_profit, entry_price) if entry_price and take_profit is not None else str(take_profit)
    risk_str = f"{risk_percent:.2f}%" if risk_percent is not None else 'N/A'
    rr_str = f"{entry_result.reward_risk:.2f}" if entry_result.reward_risk is not None else 'N/A'

    return register_and_notify_trade(
        active_trades,
        tf_loggers,
        symbol=symbol,
        strategy='MULTI_TF',
        direction='LONG',
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_percent=risk_percent,
        reward_risk=entry_result.reward_risk,
        note=one_h_summary,
        notification_message=(
            f"🎯 1H ВХОД В СДЕЛКУ!\n"
            f"{symbol}\n"
            f"Стратегия: MULTI_TF\n"
            f"Направление: LONG\n"
            f"Вход: {entry_price}\n"
            f"Стоп: {sl_str}\n"
            f"Тейк: {tp_str}\n"
            f"Риск: {risk_str}\n"
            f"R:R = {rr_str}\n\n"
            f"{one_h_summary}"
        ),
        duplicate_log_message='duplicate MULTI_TF entry ignored',
        emergency_channel='CRITICAL',
        emergency_details=f'ENTER LONG @ {entry_price}',
    )


def handle_range_signal(active_trades, tf_loggers, *, symbol, range_result):
    """Обрабатывает сигнал входа по range-стратегии."""
    direction = 'LONG' if range_result['action'] == 'BUY' else 'SHORT'
    direction_icon = '🟢 LONG' if direction == 'LONG' else '🔴 SHORT'
    entry_price = range_result['entry_price']
    stop_loss = range_result['stop_loss']
    take_profit = range_result['take_profit']
    risk_reward_ratio = range_result['risk_reward_ratio']
    confidence = range_result['confidence']

    sl_str = format_price(stop_loss, entry_price)
    tp_str = format_price(take_profit, entry_price)

    return register_and_notify_trade(
        active_trades,
        tf_loggers,
        symbol=symbol,
        strategy='RANGE',
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_percent=None,
        reward_risk=risk_reward_ratio,
        note=range_result['summary'],
        notification_message=(
            f"📊 RANGE TRADING SIGNAL (1H)!\n"
            f"{symbol}\n"
            f"{direction_icon}\n"
            f"Уверенность: {confidence}/10\n\n"
            f"Вход: {entry_price}\n"
            f"Стоп: {sl_str}\n"
            f"Тейк: {tp_str}\n"
            f"R:R = 1:{risk_reward_ratio:.2f}\n\n"
            f"Сигналы:\n" + "\n".join(range_result['signals'][:5])
        ),
        duplicate_log_message=f"duplicate RANGE {direction.lower()} entry ignored",
        emergency_channel='TELEGRAM',
        emergency_details=(
            'Range Trading signal failed' if direction == 'LONG' else 'Range Trading short signal failed'
        ),
    )