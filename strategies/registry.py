from .m15_breakout import M15BreakoutStrategy
from .support_resistance import SupportResistanceStrategy


class StrategyRegistry:
    """Current GOLD_AI market-specific routing.

    GOLD/XAUUSD:
      - refined Support & Resistance
      - restored M15 Breakout

    US30:
      - restored M15 Breakout

    Sweep & Flip is disabled from active routing.
    """

    def __init__(self, market: str | None = None, **strategy_kwargs):
        market_key = (market or "").upper()

        if market_key in {"GOLD", "XAUUSD"}:
            self.models = [
                SupportResistanceStrategy(min_stop_atr=1.5),
                M15BreakoutStrategy(),
            ]
        elif market_key in {"US30", "US30.CASH", "US30.STD"}:
            self.models = [M15BreakoutStrategy()]
        else:
            self.models = []

    def scan(self, candles):
        signals = []
        for model in self.models:
            signals.extend(model.scan(candles))
        return signals

    @property
    def strategy_ids(self):
        return [m.strategy_id for m in self.models]
