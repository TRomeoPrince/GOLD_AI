from __future__ import annotations

from .base import StrategyModel, StrategySignal


class SupportResistanceStrategy(StrategyModel):
    strategy_id = "SUPPORT_RESISTANCE"

    def scan(self, candles) -> list[StrategySignal]:
        # Independent model. It does not require another strategy to agree.
        # Exact source-derived rules are intentionally pending verification.
        return []
