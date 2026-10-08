from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class PullbackStrategy(StrategyModel):
    strategy_id="PULLBACK"
    def __init__(self, trend_bars=12, stop_atr=.2, reward_r=1.5):
        self.trend_bars=trend_bars; self.stop_atr=stop_atr; self.reward_r=reward_r
    def scan(self,candles):
        if candles is None or len(candles)<40:return []
        f=candles.iloc[:-1].copy().reset_index(drop=True); f["atr"]=atr(f,14)
        last=f.iloc[-1]; a=float(last.atr) if pd.notna(last.atr) else 0
        if a<=0:return []
        w=f.iloc[-self.trend_bars-1:-1]; c=float(last.close); o=float(last.open)
        out=[]
        rising=float(w.close.iloc[-1])>float(w.close.iloc[0]); falling=not rising
        recent_low=float(w.low.tail(5).min()); recent_high=float(w.high.tail(5).max())
        if rising and float(last.low)<=recent_low+.25*a and c>o:
            sl=float(last.low)-self.stop_atr*a; r=c-sl
            if r>0: out.append(StrategySignal(self.strategy_id,"BUY","M5",str(last.time),c,sl,c+self.reward_r*r,"TREND_PULLBACK_CONTINUATION",{"trend":"UP","atr":a}))
        if falling and float(last.high)>=recent_high-.25*a and c<o:
            sl=float(last.high)+self.stop_atr*a; r=sl-c
            if r>0: out.append(StrategySignal(self.strategy_id,"SELL","M5",str(last.time),c,sl,c-self.reward_r*r,"TREND_PULLBACK_CONTINUATION",{"trend":"DOWN","atr":a}))
        return out
