from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StrategySignal:
    strategy_name: str
    symbol: str
    timeframe: str
    stage: str
    action: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyRuntimeConfig:
    enabled: bool = True
    watch_only: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyContext:
    symbol: str
    tracker: Any
    tf_loggers: dict[str, Any]
    market_data_provider: Any


class BaseStrategy(ABC):
    name: str

    def __init__(self, runtime_config: StrategyRuntimeConfig | None = None):
        self.runtime_config = runtime_config or StrategyRuntimeConfig()

    @property
    def enabled(self) -> bool:
        return self.runtime_config.enabled

    @property
    def watch_only(self) -> bool:
        return self.runtime_config.watch_only

    def get_parameter(self, key: str, default: Any = None) -> Any:
        return self.runtime_config.parameters.get(key, default)

    @abstractmethod
    def analyze_symbol(self, context: StrategyContext) -> list[StrategySignal]:
        raise NotImplementedError