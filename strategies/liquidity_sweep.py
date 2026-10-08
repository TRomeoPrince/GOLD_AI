from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class LiquiditySweepStrategy(StrategyModel):
    strategy_id="LIQUIDITY_SWEEP"
    def __init__(self, lookback=20, stop_atr=.15, reward_r=2.0):
        self.lookback=lookback; self.stop_atr=stop_atr; self.reward_r=reward_r
    def scan(self,candles):
        if candles is None or len(candles)<45:return []
        f=candles.iloc[:-1].copy().reset_index(drop=True); f["atr"]=atr(f,14)
        last=f.iloc[-1]; prior=f.iloc[-1-self.lookback:-1]
        a=float(last.atr) if pd.notna(last.atr) else 0
        if a<=0:return []
        ph=float(prior.high.max()); pl=float(prior.low.min()); c=float(last.close); o=float(last.open)
        out=[]
        if float(last.low)<pl and c>pl and c>o:
            sl=float(last.low)-self.stop_atr*a; r=c-sl
            if r>0: out.append(StrategySignal(self.strategy_id,"BUY","M5",str(last.time),c,sl,c+self.reward_r*r,"SELL_SIDE_LIQUIDITY_SWEEP_RECLAIM",{"liquidity_level":pl,"atr":a}))
        if float(last.high)>ph and c<ph and c<o:
            sl=float(last.high)+self.stop_atr*a; r=sl-c
            if r>0: out.append(StrategySignal(self.strategy_id,"SELL","M5",str(last.time),c,sl,c-self.reward_r*r,"BUY_SIDE_LIQUIDITY_SWEEP_RECLAIM",{"liquidity_level":ph,"atr":a}))
        return out
