from __future__ import annotations

from .base import StrategyModel, StrategySignal


class RangeBreakStrategy(StrategyModel):
    strategy_id = "RANGE_BREAK"

    def scan(self, candles) -> list[StrategySignal]:
        # Independent model. Exact source-derived breakout/retest rules are
        # intentionally pending verification rather than guessed from titles.
        return []
