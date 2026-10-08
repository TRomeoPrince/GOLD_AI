from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class PriceActionStrategy(StrategyModel):
    strategy_id="PRICE_ACTION"
    def __init__(self, stop_atr=.15, reward_r=1.5):
        self.stop_atr=stop_atr; self.reward_r=reward_r
    def scan(self,candles):
        if candles is None or len(candles)<25:return []
        f=candles.iloc[:-1].copy().reset_index(drop=True); f["atr"]=atr(f,14)
        p=f.iloc[-2]; x=f.iloc[-1]; a=float(x.atr) if pd.notna(x.atr) else 0
        if a<=0:return []
        out=[]; c=float(x.close)
        bull=float(x.close)>float(x.open) and float(x.open)<=float(p.close) and float(x.close)>=float(p.open) and float(p.close)<float(p.open)
        bear=float(x.close)<float(x.open) and float(x.open)>=float(p.close) and float(x.close)<=float(p.open) and float(p.close)>float(p.open)
        if bull:
            sl=min(float(x.low),float(p.low))-self.stop_atr*a; r=c-sl
            if r>0:out.append(StrategySignal(self.strategy_id,"BUY","M5",str(x.time),c,sl,c+self.reward_r*r,"BULLISH_ENGULFING",{"atr":a}))
        if bear:
            sl=max(float(x.high),float(p.high))+self.stop_atr*a; r=sl-c
            if r>0:out.append(StrategySignal(self.strategy_id,"SELL","M5",str(x.time),c,sl,c-self.reward_r*r,"BEARISH_ENGULFING",{"atr":a}))
        return out
