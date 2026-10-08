from .market_structure import MarketStructureStrategy
from .support_resistance import SupportResistanceStrategy
from .range_break import RangeBreakStrategy
from .smart_money_5m import SmartMoney5MStrategy
from .pullback import PullbackStrategy
from .momentum_scalp import MomentumScalpStrategy

class StrategyRegistry:
    """Active research portfolio.

    Baseline 001 losers are retained in source but excluded from the active
    registry so they can be re-tested later without losing their implementation.
    """
    def __init__(self):
        self.models=[
            MarketStructureStrategy(),
            SupportResistanceStrategy(),
            RangeBreakStrategy(),
            SmartMoney5MStrategy(),
            PullbackStrategy(),
            MomentumScalpStrategy(),
        ]

    def scan(self,candles):
        signals=[]
        for model in self.models:
            signals.extend(model.scan(candles))
        return signals

    @property
    def strategy_ids(self):
        return [m.strategy_id for m in self.models]
