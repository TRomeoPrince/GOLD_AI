from .m15_breakout import M15BreakoutStrategy
from .market_structure import MarketStructureStrategy
from .momentum_scalp import MomentumScalpStrategy
from .pullback import PullbackStrategy
from .support_resistance import SupportResistanceStrategy


class StrategyRegistry:
    """Current GOLD_AI market-specific routing.

    GOLD/XAUUSD:
      - refined Support & Resistance
      - Market Structure
      - Pullback
      - Momentum Scalp
      - M15 Breakout

    US30:
      - Market Structure
      - Pullback
      - Momentum Scalp
      - M15 Breakout

    Sweep & Flip remains disabled.

    Risk sizing is NOT controlled here. All active strategies continue through
    the shared executor, so the configured per-trade and portfolio risk guards
    remain unchanged.
    """

    def __init__(self, market: str | None = None, **strategy_kwargs):
        market_key = (market or "").upper()

        shared = [
            MarketStructureStrategy(),
            PullbackStrategy(),
            MomentumScalpStrategy(min_stop_atr=1.5),
            M15BreakoutStrategy(),
        ]

        if market_key in {"GOLD", "XAUUSD"}:
            self.models = [
                SupportResistanceStrategy(min_stop_atr=1.5),
                *shared,
            ]
        elif market_key in {"US30", "US30.CASH", "US30.STD"}:
            self.models = shared
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
