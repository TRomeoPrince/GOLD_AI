from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class PowerOfThreeStrategy(StrategyModel):
    strategy_id="POWER_OF_THREE"
    def __init__(self, accumulation_bars=8, stop_atr=.15, reward_r=2.0):
        self.accumulation_bars=accumulation_bars; self.stop_atr=stop_atr; self.reward_r=reward_r
    def scan(self,candles):
        if candles is None or len(candles)<45:return []
        f=candles.iloc[:-1].copy().reset_index(drop=True); f["atr"]=atr(f,14)
        last=f.iloc[-1]; base=f.iloc[-1-self.accumulation_bars:-1]
        a=float(last.atr) if pd.notna(last.atr) else 0
        if a<=0:return []
        hi=float(base.high.max()); lo=float(base.low.min()); c=float(last.close); o=float(last.open)
        out=[]
        # Accumulation -> manipulation outside range -> close/reclaim toward distribution.
        if float(last.low)<lo and c>lo and c>o:
            sl=float(last.low)-self.stop_atr*a; r=c-sl
            if r>0: out.append(StrategySignal(self.strategy_id,"BUY","M5",str(last.time),c,sl,c+self.reward_r*r,"ACCUMULATION_LOW_MANIPULATION",{"accumulation_high":hi,"accumulation_low":lo}))
        if float(last.high)>hi and c<hi and c<o:
            sl=float(last.high)+self.stop_atr*a; r=sl-c
            if r>0: out.append(StrategySignal(self.strategy_id,"SELL","M5",str(last.time),c,sl,c-self.reward_r*r,"ACCUMULATION_HIGH_MANIPULATION",{"accumulation_high":hi,"accumulation_low":lo}))
        return out
