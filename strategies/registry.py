from __future__ import annotations

from .market_structure import MarketStructureStrategy
from .range_break import RangeBreakStrategy
from .support_resistance import SupportResistanceStrategy


class StrategyRegistry:
    def __init__(self) -> None:
        self.models = [
            MarketStructureStrategy(),
            SupportResistanceStrategy(),
            RangeBreakStrategy(),
        ]

    def scan(self, candles):
        signals = []
        for model in self.models:
            signals.extend(model.scan(candles))
        return signals

    @property
    def strategy_ids(self) -> list[str]:
        return [model.strategy_id for model in self.models]
