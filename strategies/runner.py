from __future__ import annotations

from strategies.base import BaseStrategy, StrategyContext, StrategySignal


class StrategyRunner:
    def __init__(self, strategies: list[BaseStrategy]):
        self.strategies = strategies

    def analyze_symbol(self, context: StrategyContext) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        for strategy in self.strategies:
            if not strategy.enabled:
                continue
            signals.extend(strategy.analyze_symbol(context))
        return signals