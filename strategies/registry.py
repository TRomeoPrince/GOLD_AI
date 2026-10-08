from .market_structure import MarketStructureStrategy
from .support_resistance import SupportResistanceStrategy
from .range_break import RangeBreakStrategy
from .smart_money_5m import SmartMoney5MStrategy
from .pullback import PullbackStrategy
from .liquidity_sweep import LiquiditySweepStrategy
from .power_of_three import PowerOfThreeStrategy
from .price_action import PriceActionStrategy
from .momentum_scalp import MomentumScalpStrategy

class StrategyRegistry:
    def __init__(self):
        self.models=[MarketStructureStrategy(),SupportResistanceStrategy(),RangeBreakStrategy(),
                     SmartMoney5MStrategy(),PullbackStrategy(),LiquiditySweepStrategy(),
                     PowerOfThreeStrategy(),PriceActionStrategy(),MomentumScalpStrategy()]
    def scan(self,candles):
        signals=[]
        for model in self.models: signals.extend(model.scan(candles))
        return signals
    @property
    def strategy_ids(self): return [m.strategy_id for m in self.models]
