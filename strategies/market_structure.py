from __future__ import annotations

from .base import StrategyModel, StrategySignal


class MarketStructureStrategy(StrategyModel):
    strategy_id = "MARKET_STRUCTURE"

    def scan(self, candles) -> list[StrategySignal]:
        # Framework only: exact video-derived entry/invalidation rules will be
        # added after they are extracted and verified. Do not invent them.
        return []
