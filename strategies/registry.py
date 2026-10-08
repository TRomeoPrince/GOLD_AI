from .market_structure import MarketStructureStrategy
from .support_resistance import SupportResistanceStrategy
from .range_break import RangeBreakStrategy
from .smart_money_5m import SmartMoney5MStrategy
from .pullback import PullbackStrategy
from .momentum_scalp import MomentumScalpStrategy
from .liquidity_sweep import LiquiditySweepStrategy

class StrategyRegistry:
    """Active research portfolio using only each strategy's current version.

    Standalone PRICE_ACTION and POWER_OF_THREE remain preserved in source but
    inactive. Liquidity Sweep is active only in its Price-Action-confirmed form.
    """
    def __init__(self):
        self.models=[
            MarketStructureStrategy(),
            SupportResistanceStrategy(),
            RangeBreakStrategy(),
            SmartMoney5MStrategy(),
            PullbackStrategy(),
            MomentumScalpStrategy(),
            LiquiditySweepStrategy(),
        ]

    def scan(self,candles):
        signals=[]
        for model in self.models:
            signals.extend(model.scan(candles))
        return signals

    @property
    def strategy_ids(self):
        return [m.strategy_id for m in self.models]
