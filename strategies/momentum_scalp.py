from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr


class MomentumScalpStrategy(StrategyModel):
    strategy_id = "MOMENTUM_SCALP"

    def __init__(
        self,
        body_atr=.9,
        body_ratio=.65,
        stop_atr=.2,
        reward_r=1.25,
        min_stop_atr=1.5,
    ):
        self.body_atr = body_atr
        self.body_ratio = body_ratio
        self.stop_atr = stop_atr
        self.reward_r = reward_r
        self.min_stop_atr = min_stop_atr

    def scan(self, candles):
        if candles is None or len(candles) < 25:
            return []

        f = candles.iloc[:-1].copy().reset_index(drop=True)
        f["atr"] = atr(f, 14)
        x = f.iloc[-1]

        a = float(x.atr) if pd.notna(x.atr) else 0.0
        rng = float(x.high - x.low)
        body = abs(float(x.close - x.open))
        if a <= 0 or rng <= 0 or body < a * self.body_atr or body / rng < self.body_ratio:
            return []

        c = float(x.close)
        out = []

        # Momentum already uses the displacement candle extreme as structural
        # invalidation. Refined v1 adds only a minimum ATR breathing-room floor.
        if c > float(x.open):
            structural_sl = float(x.low) - self.stop_atr * a
            volatility_floor = c - self.min_stop_atr * a
            sl = min(structural_sl, volatility_floor)
            r = c - sl
            if r > 0:
                out.append(
                    StrategySignal(
                        self.strategy_id,
                        "BUY",
                        "M5",
                        str(x.time),
                        c,
                        sl,
                        c + self.reward_r * r,
                        "BULLISH_MOMENTUM_REFINED_INVALIDATION",
                        {
                            "body_atr": body / a,
                            "body_ratio": body / rng,
                            "atr": a,
                            "min_stop_atr": self.min_stop_atr,
                        },
                    )
                )
        else:
            structural_sl = float(x.high) + self.stop_atr * a
            volatility_floor = c + self.min_stop_atr * a
            sl = max(structural_sl, volatility_floor)
            r = sl - c
            if r > 0:
                out.append(
                    StrategySignal(
                        self.strategy_id,
                        "SELL",
                        "M5",
                        str(x.time),
                        c,
                        sl,
                        c - self.reward_r * r,
                        "BEARISH_MOMENTUM_REFINED_INVALIDATION",
                        {
                            "body_atr": body / a,
                            "body_ratio": body / rng,
                            "atr": a,
                            "min_stop_atr": self.min_stop_atr,
                        },
                    )
                )

        return out
