from .m15_sweep_flip import M15SweepFlipStrategy
from .support_resistance import SupportResistanceStrategy


class StrategyRegistry:
    """Current GOLD_AI market-specific strategy routing.

    GOLD/XAUUSD: refined Support & Resistance (the strongest long-run Gold
    candidate from the previous research cycle).

    US30: video-derived M15 Sweep & Flip with structure trailing handled by the
    execution layer.

    No other legacy strategies are enabled by this registry.
    """

    def __init__(self, market: str | None = None, **strategy_kwargs):
        market_key = (market or "").upper()

        if market_key in {"GOLD", "XAUUSD"}:
            # Gold-only restoration requested by the user.
            self.models = [SupportResistanceStrategy(min_stop_atr=1.5)]
        elif market_key in {"US30", "US30.CASH", "US30.STD"}:
            self.models = [M15SweepFlipStrategy(**strategy_kwargs)]
        else:
            # Do not silently route unsupported/deprecated markets.
            self.models = []

    def scan(self, candles):
        signals = []
        for model in self.models:
            signals.extend(model.scan(candles))
        return signals

    @property
    def strategy_ids(self):
        return [m.strategy_id for m in self.models]
