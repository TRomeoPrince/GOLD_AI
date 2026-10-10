from .m15_sweep_flip import M15SweepFlipStrategy


class StrategyRegistry:
    """Current GOLD_AI research registry.

    The old six-strategy and market-specific S/R/Momentum routing is deprecated.
    Current strategy direction is M15 Sweep & Flip only.
    """

    def __init__(self, market: str | None = None, **strategy_kwargs):
        self.models = [M15SweepFlipStrategy(**strategy_kwargs)]

    def scan(self, candles):
        signals = []
        for model in self.models:
            signals.extend(model.scan(candles))
        return signals

    @property
    def strategy_ids(self):
        return [m.strategy_id for m in self.models]
