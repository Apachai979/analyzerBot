from __future__ import annotations

from config import STRATEGY_RUNTIME_CONFIGS
from strategies.base import BaseStrategy, StrategyRuntimeConfig
from strategies.multi_tf_trend_strategy import MultiTimeframeTrendStrategy
from strategies.range_trading_strategy import RangeTradingStrategy


def resolve_runtime_config(strategy_name: str) -> StrategyRuntimeConfig:
    config = STRATEGY_RUNTIME_CONFIGS.get(strategy_name, {})
    return StrategyRuntimeConfig(
        enabled=bool(config.get('enabled', True)),
        watch_only=bool(config.get('watch_only', False)),
        parameters=dict(config.get('parameters', {})),
    )


def build_default_strategies() -> list[BaseStrategy]:
    return [
        MultiTimeframeTrendStrategy(runtime_config=resolve_runtime_config('MULTI_TF')),
        RangeTradingStrategy(runtime_config=resolve_runtime_config('RANGE')),
    ]