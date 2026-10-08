from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class SupportResistanceStrategy(StrategyModel):
    strategy_id = "SUPPORT_RESISTANCE"

    def __init__(self, lookback=80, pivot_span=2, cluster_atr=0.20,
                 touch_atr=0.18, stop_atr=0.18, reward_r=1.5):
        self.lookback=lookback; self.pivot_span=pivot_span
        self.cluster_atr=cluster_atr; self.touch_atr=touch_atr
        self.stop_atr=stop_atr; self.reward_r=reward_r

    def _pivots(self, f):
        hs=[]; ls=[]; s=self.pivot_span
        for i in range(s, len(f)-s):
            w=f.iloc[i-s:i+s+1]
            if f.iloc[i].high >= w.high.max(): hs.append(float(f.iloc[i].high))
            if f.iloc[i].low <= w.low.min(): ls.append(float(f.iloc[i].low))
        return hs,ls

    def _level(self, values, tol):
        if len(values)<2: return None
        best=None
        for v in values:
            group=[x for x in values if abs(x-v)<=tol]
            if len(group)>=2 and (best is None or len(group)>len(best)):
                best=group
        return sum(best)/len(best) if best else None

    def scan(self, candles):
        if candles is None or len(candles)<50: return []
        f=candles.iloc[:-1].tail(self.lookback).copy().reset_index(drop=True)
        f["atr"]=atr(f,14); last=f.iloc[-1]
        a=float(last.atr) if pd.notna(last.atr) else 0.0
        if a<=0: return []
        hs,ls=self._pivots(f)
        resistance=self._level(hs,a*self.cluster_atr)
        support=self._level(ls,a*self.cluster_atr)
        out=[]; o=float(last.open); c=float(last.close); h=float(last.high); l=float(last.low)
        if support is not None and l <= support+a*self.touch_atr and c>support and c>o:
            sl=support-a*self.stop_atr; risk=c-sl
            if risk>0: out.append(StrategySignal(self.strategy_id,"BUY","M5",str(last.time),c,sl,c+self.reward_r*risk,
                "SUPPORT_REJECTION",{"support":support,"atr":a,"reward_r":self.reward_r}))
        if resistance is not None and h >= resistance-a*self.touch_atr and c<resistance and c<o:
            sl=resistance+a*self.stop_atr; risk=sl-c
            if risk>0: out.append(StrategySignal(self.strategy_id,"SELL","M5",str(last.time),c,sl,c-self.reward_r*risk,
                "RESISTANCE_REJECTION",{"resistance":resistance,"atr":a,"reward_r":self.reward_r}))
        return out
