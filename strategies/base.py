from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Direction = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class StrategySignal:
    strategy_id: str
    direction: Direction
    timeframe: str
    setup_time: str
    entry: float
    stop_loss: float
    take_profit: float
    reason: str
    features: dict[str, Any] = field(default_factory=dict)


class StrategyModel(ABC):
    strategy_id: str

    @abstractmethod
    def scan(self, candles) -> list[StrategySignal]:
        """Return only setups valid under this strategy's own rules."""
        raise NotImplementedError
