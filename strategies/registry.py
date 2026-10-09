from .market_structure import MarketStructureStrategy
from .support_resistance import SupportResistanceStrategy
from .range_break import RangeBreakStrategy
from .smart_money_5m import SmartMoney5MStrategy
from .pullback import PullbackStrategy
from .momentum_scalp import MomentumScalpStrategy


class StrategyRegistry:
    """Strategy collection.

    With no market supplied this preserves the historical six-model registry
    used by the generic backtester. Active demo execution uses market-specific
    routing via the market argument.
    """

    def __init__(self, market: str | None = None, min_stop_atr: float = 1.5):
        market_key = (market or "").upper()

        if market_key in {"GOLD", "XAUUSD"}:
            # Long-run refined research leader for Gold.
            self.models = [
                SupportResistanceStrategy(min_stop_atr=min_stop_atr),
            ]
        elif market_key in {"US30", "US30.CASH"}:
            # Long-run refined research leader for US30.
            self.models = [
                MomentumScalpStrategy(min_stop_atr=min_stop_atr),
            ]
        else:
            # Historical/default registry retained for research compatibility.
            self.models = [
                MarketStructureStrategy(),
                SupportResistanceStrategy(),
                RangeBreakStrategy(),
                SmartMoney5MStrategy(),
                PullbackStrategy(),
                MomentumScalpStrategy(),
            ]

    def scan(self, candles):
        signals = []
        for model in self.models:
            signals.extend(model.scan(candles))
        return signals

    @property
    def strategy_ids(self):
        return [m.strategy_id for m in self.models]
