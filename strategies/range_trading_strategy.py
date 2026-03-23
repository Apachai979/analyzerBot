from __future__ import annotations

from range_trading import analyze_range_trading_signal
from trade_signal_service import handle_range_signal

from strategies.base import BaseStrategy, StrategyContext, StrategySignal
from strategies.utils import format_price


class RangeTradingStrategy(BaseStrategy):
    name = 'RANGE'

    def analyze_symbol(self, context: StrategyContext) -> list[StrategySignal]:
        symbol = context.symbol
        tracker = context.tracker
        tf_loggers = context.tf_loggers
        min_confidence = int(self.get_parameter('min_confidence', 9))
        min_risk_reward_ratio = float(self.get_parameter('min_risk_reward_ratio', 7))

        if not tracker.should_analyze(symbol, 'RANGE'):
            return []

        df_1h_range = context.market_data_provider.get_klines(symbol, interval='60')
        range_result = analyze_range_trading_signal(df_1h_range, symbol)
        if not range_result or range_result.get('action') not in ['BUY', 'SELL']:
            return []

        entry_price = range_result['entry_price']
        stop_loss = range_result['stop_loss']
        take_profit = range_result['take_profit']
        risk_reward_ratio = range_result['risk_reward_ratio']
        confidence = range_result['confidence']

        sl_str = format_price(stop_loss, entry_price)
        tp_str = format_price(take_profit, entry_price)
        summary = (
            f"RANGE 1H: {range_result['action']}\n"
            f"Confidence: {confidence}/10 | Entry: {entry_price} | SL: {sl_str} | TP: {tp_str} | R:R = 1:{risk_reward_ratio:.2f}\n"
            f"Summary: {range_result['summary']}"
        )

        tf_loggers['RANGE'].info(
            f"{symbol} | Strategy: {self.name} | Action: {range_result['action']} | "
            f"Confidence: {confidence}/10 | Entry: {entry_price} | SL: {sl_str} | TP: {tp_str} | "
            f"R:R = 1:{risk_reward_ratio:.2f} | {range_result['summary']}"
        )

        should_route_signal = (
            not self.watch_only and
            confidence >= min_confidence and
            risk_reward_ratio >= min_risk_reward_ratio and
            tracker.should_send_signal(symbol, range_result['action'], 'RANGE')
        )
        if should_route_signal:
            handle_range_signal(
                tracker.active_trades,
                tf_loggers,
                symbol=symbol,
                range_result=range_result,
            )

        return [
            StrategySignal(
                strategy_name=self.name,
                symbol=symbol,
                timeframe='1H',
                stage='trigger',
                action=range_result['action'],
                summary=summary,
                details={
                    'confidence': confidence,
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'risk_reward_ratio': risk_reward_ratio,
                    'summary': range_result['summary'],
                    'signals': range_result.get('signals', []),
                    'routed': should_route_signal,
                    'watch_only': self.watch_only,
                    'strategy_parameters': self.runtime_config.parameters,
                },
            )
        ]