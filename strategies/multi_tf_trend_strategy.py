from __future__ import annotations

import logging

from analyzes.entry_trigger_1h import EntryTrigger1hConfig, entry_trigger_1h
from analyzes.setup_filter_4h import SetupFilter4hConfig, setup_filter_4h
from analyzes.trend_filter_12h_v2 import TrendFilter12hConfig, trend_filter_12h
from telegram_utils import send_emergency_alert, send_telegram_message
from trade_signal_service import handle_multitimeframe_entry_signal

from strategies.base import BaseStrategy, StrategyContext, StrategySignal
from strategies.utils import (
    derive_filter_action,
    format_trigger_summary,
    format_setup_summary,
    format_bias_summary,
    prepare_ohlcv_for_filter,
)


class MultiTimeframeTrendStrategy(BaseStrategy):
    name = 'MULTI_TF'

    def _state_key(self, suffix: str) -> str:
        return f'{self.name}:{suffix}'

    def analyze_symbol(self, context: StrategyContext) -> list[StrategySignal]:
        symbol = context.symbol
        tracker = context.tracker
        tf_loggers = context.tf_loggers
        signals: list[StrategySignal] = []
        trend_min_required_rows = int(self.get_parameter('trend_min_required_rows', 260))
        trend_min_soft_conditions_passed = int(self.get_parameter('trend_min_soft_conditions_passed', 2))
        setup_min_required_rows = int(self.get_parameter('setup_min_required_rows', 220))
        setup_min_soft_conditions_passed = int(self.get_parameter('setup_min_soft_conditions_passed', 6))
        entry_min_required_rows = int(self.get_parameter('entry_min_required_rows', 180))
        entry_min_soft_conditions_passed = int(self.get_parameter('entry_min_soft_conditions_passed', 5))

        if symbol not in tracker.last_analysis:
            tracker.last_analysis[symbol] = {}

        twelve_h_key = self._state_key('twelve_h_result')
        four_h_key = self._state_key('four_h_result')

        if tracker.should_analyze(symbol, '12H'):
            raw_12h = context.market_data_provider.get_klines(symbol, interval='720')
            df_12h = prepare_ohlcv_for_filter(raw_12h, interval_minutes=720, drop_incomplete_last_candle=True)

            if df_12h.empty:
                tracker.last_analysis[symbol].pop(twelve_h_key, None)
                tracker.last_analysis[symbol].pop(four_h_key, None)
                return signals

            twelve_h_result = trend_filter_12h(
                df_12h,
                config=TrendFilter12hConfig(
                    min_required_rows=trend_min_required_rows,
                    min_soft_conditions_passed=trend_min_soft_conditions_passed,
                ),
            )
            twelve_h_action = derive_filter_action(
                passed=twelve_h_result.passed,
                hard_passed=twelve_h_result.hard_passed,
                soft_score=twelve_h_result.soft_score,
                required_score=twelve_h_result.details.get('soft_score_required', twelve_h_result.soft_score_max),
            )
            twelve_h_summary = format_bias_summary('12H', twelve_h_result)

            print(f"[12H] {symbol}\n{twelve_h_summary}")
            logging.info(f"[12H] {symbol} → {twelve_h_action}")
            tf_loggers['12H'].info(
                f"{symbol} | Strategy: {self.name} | Action: {twelve_h_action} | {twelve_h_summary.replace(chr(10), ' | ')}"
            )
            signals.append(
                StrategySignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe='12H',
                    stage='bias',
                    action=twelve_h_action,
                    summary=twelve_h_summary,
                    details={
                        **twelve_h_result.details,
                        'watch_only': self.watch_only,
                        'strategy_parameters': self.runtime_config.parameters,
                    },
                )
            )

            if twelve_h_action in ['GO', 'ATTENTION']:
                tracker.last_analysis[symbol][twelve_h_key] = {
                    'action': twelve_h_action,
                    'summary': twelve_h_summary,
                    'result': twelve_h_result,
                }
            else:
                tracker.last_analysis[symbol].pop(twelve_h_key, None)
                tracker.last_analysis[symbol].pop(four_h_key, None)
                return signals

        twelve_h_state = tracker.last_analysis.get(symbol, {}).get(twelve_h_key)
        if not twelve_h_state or twelve_h_state.get('action') not in ['GO', 'ATTENTION']:
            return signals

        if tracker.should_analyze(symbol, '4H'):
            raw_4h = context.market_data_provider.get_klines(symbol, interval='240')
            df_4h = prepare_ohlcv_for_filter(raw_4h, interval_minutes=240, drop_incomplete_last_candle=True)

            if df_4h.empty:
                tracker.last_analysis[symbol].pop(four_h_key, None)
                return signals

            four_h_result = setup_filter_4h(
                df_4h,
                trend_bias_passed=twelve_h_state['result'].passed,
                trend_bias_reason=twelve_h_state['result'].reason,
                config=SetupFilter4hConfig(
                    min_required_rows=setup_min_required_rows,
                    min_soft_conditions_passed=setup_min_soft_conditions_passed,
                ),
            )
            four_h_action = derive_filter_action(
                passed=four_h_result.passed,
                hard_passed=four_h_result.hard_passed,
                soft_score=four_h_result.soft_score,
                required_score=four_h_result.details.get('soft_score_required', four_h_result.soft_score_max),
            )
            four_h_summary = format_setup_summary('4H', four_h_result)

            print(f"[4H] {symbol}\n{four_h_summary}")
            logging.info(f"[4H] {symbol} → {four_h_action}")
            tf_loggers['4H'].info(
                f"{symbol} | Strategy: {self.name} | Action: {four_h_action} | {four_h_summary.replace(chr(10), ' | ')}"
            )
            signals.append(
                StrategySignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe='4H',
                    stage='setup',
                    action=four_h_action,
                    summary=four_h_summary,
                    details={
                        **four_h_result.details,
                        'watch_only': self.watch_only,
                        'strategy_parameters': self.runtime_config.parameters,
                    },
                )
            )

            if four_h_action in ['GO', 'ATTENTION']:
                tracker.last_analysis[symbol][four_h_key] = {
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
                tracker.last_analysis[symbol].pop(four_h_key, None)
                return signals

        four_h_state = tracker.last_analysis.get(symbol, {}).get(four_h_key)
        if not four_h_state or four_h_state.get('action') not in ['GO', 'ATTENTION']:
            return signals

        if tracker.should_analyze(symbol, '1H'):
            raw_1h = context.market_data_provider.get_klines(symbol, interval='60')
            df_1h = prepare_ohlcv_for_filter(raw_1h, interval_minutes=60, drop_incomplete_last_candle=True)

            if df_1h.empty:
                return signals

            one_h_result = entry_trigger_1h(
                df_1h,
                setup_result=four_h_state['result'],
                config=EntryTrigger1hConfig(
                    min_required_rows=entry_min_required_rows,
                    min_soft_conditions_passed=entry_min_soft_conditions_passed,
                ),
            )

            one_h_summary = format_trigger_summary('1H', one_h_result)
            print(f"[1H] {symbol}\n{one_h_summary}")
            logging.info(f"[1H] {symbol} → {one_h_result.action}")
            tf_loggers['1H'].info(
                f"{symbol} | Strategy: {self.name} | Action: {one_h_result.action} | {one_h_summary.replace(chr(10), ' | ')}"
            )
            signals.append(
                StrategySignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe='1H',
                    stage='trigger',
                    action=one_h_result.action,
                    summary=one_h_summary,
                    details={
                        **one_h_result.details,
                        'watch_only': self.watch_only,
                        'strategy_parameters': self.runtime_config.parameters,
                    },
                )
            )

            if one_h_result.action == 'ENTER' and not self.watch_only:
                handle_multitimeframe_entry_signal(
                    tracker.active_trades,
                    tf_loggers,
                    symbol=symbol,
                    entry_result=one_h_result,
                    one_h_summary=one_h_summary,
                )
            elif one_h_result.action == 'ENTER' and self.watch_only:
                tf_loggers['MONITOR'].info(
                    f"{symbol} | Strategy: {self.name} | watch_only=true | ENTER not routed"
                )
            elif one_h_result.action == 'WAIT_BETTER':
                success = send_telegram_message(
                    f"🟡 1H ЖДАТЬ ЛУЧШЕЙ ЦЕНЫ\n{symbol}\n{one_h_summary}"
                )
                if not success:
                    send_emergency_alert('TELEGRAM', symbol=symbol, details='WAIT signal failed')

        return signals