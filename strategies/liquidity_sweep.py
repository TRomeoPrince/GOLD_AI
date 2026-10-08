from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class LiquiditySweepStrategy(StrategyModel):
    """Liquidity sweep refined with price-action confirmation.

    A sweep/reclaim alone is not enough. The reclaim candle must also form
    a directional engulfing pattern against the candle immediately before it.
    This keeps Price Action as confirmation instead of an independent model.
    """
    strategy_id="LIQUIDITY_SWEEP_PA"

    def __init__(self, lookback=20, stop_atr=.15, reward_r=2.0):
        self.lookback=lookback
        self.stop_atr=stop_atr
        self.reward_r=reward_r

    def scan(self,candles):
        if candles is None or len(candles)<45:
            return []

        f=candles.iloc[:-1].copy().reset_index(drop=True)
        f["atr"]=atr(f,14)
        last=f.iloc[-1]
        prev=f.iloc[-2]
        prior=f.iloc[-1-self.lookback:-1]
        a=float(last.atr) if pd.notna(last.atr) else 0
        if a<=0:
            return []

        ph=float(prior.high.max())
        pl=float(prior.low.min())
        c=float(last.close)
        o=float(last.open)

        bull_engulf=(
            c>o
            and float(prev.close)<float(prev.open)
            and o<=float(prev.close)
            and c>=float(prev.open)
        )
        bear_engulf=(
            c<o
            and float(prev.close)>float(prev.open)
            and o>=float(prev.close)
            and c<=float(prev.open)
        )

        out=[]
        if float(last.low)<pl and c>pl and bull_engulf:
            sl=min(float(last.low),float(prev.low))-self.stop_atr*a
            r=c-sl
            if r>0:
                out.append(StrategySignal(
                    self.strategy_id,"BUY","M5",str(last.time),c,sl,
                    c+self.reward_r*r,
                    "SELL_SIDE_LIQUIDITY_SWEEP_RECLAIM_BULLISH_ENGULF",
                    {"liquidity_level":pl,"atr":a,"confirmation":"BULLISH_ENGULFING"}
                ))

        if float(last.high)>ph and c<ph and bear_engulf:
            sl=max(float(last.high),float(prev.high))+self.stop_atr*a
            r=sl-c
            if r>0:
                out.append(StrategySignal(
                    self.strategy_id,"SELL","M5",str(last.time),c,sl,
                    c-self.reward_r*r,
                    "BUY_SIDE_LIQUIDITY_SWEEP_RECLAIM_BEARISH_ENGULF",
                    {"liquidity_level":ph,"atr":a,"confirmation":"BEARISH_ENGULFING"}
                ))
        return out
