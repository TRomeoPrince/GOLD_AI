from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class RangeBreakStrategy(StrategyModel):
    strategy_id="RANGE_BREAK"

    def __init__(self, range_bars=12, max_range_atr=4.0, breakout_body_atr=0.55,
                 retest_atr=0.20, stop_atr=0.18, reward_r=1.5):
        self.range_bars=range_bars; self.max_range_atr=max_range_atr
        self.breakout_body_atr=breakout_body_atr; self.retest_atr=retest_atr
        self.stop_atr=stop_atr; self.reward_r=reward_r

    def scan(self,candles):
        if candles is None or len(candles)<40:return []
        f=candles.iloc[:-1].copy().reset_index(drop=True); f["atr"]=atr(f,14)
        if len(f)<self.range_bars+3:return []
        ret=f.iloc[-1]; br=f.iloc[-2]
        a=float(br.atr) if pd.notna(br.atr) else 0.0
        if a<=0:return []
        base=f.iloc[-2-self.range_bars:-2]
        hi=float(base.high.max()); lo=float(base.low.min())
        if hi-lo > self.max_range_atr*a:return []
        body=abs(float(br.close)-float(br.open))
        if body < self.breakout_body_atr*a:return []
        out=[]; tol=self.retest_atr*a
        if float(br.close)>hi and float(br.close)>float(br.open):
            retest=float(ret.low)<=hi+tol and float(ret.close)>hi and float(ret.close)>float(ret.open)
            if retest:
                entry=float(ret.close); sl=min(float(ret.low),hi)-self.stop_atr*a; risk=entry-sl
                if risk>0: out.append(StrategySignal(self.strategy_id,"BUY","M5",str(ret.time),entry,sl,entry+self.reward_r*risk,
                    "RANGE_HIGH_BREAK_RETEST",{"range_high":hi,"range_low":lo,"breakout_body_atr":body/a,"reward_r":self.reward_r}))
        if float(br.close)<lo and float(br.close)<float(br.open):
            retest=float(ret.high)>=lo-tol and float(ret.close)<lo and float(ret.close)<float(ret.open)
            if retest:
                entry=float(ret.close); sl=max(float(ret.high),lo)+self.stop_atr*a; risk=sl-entry
                if risk>0: out.append(StrategySignal(self.strategy_id,"SELL","M5",str(ret.time),entry,sl,entry-self.reward_r*risk,
                    "RANGE_LOW_BREAK_RETEST",{"range_high":hi,"range_low":lo,"breakout_body_atr":body/a,"reward_r":self.reward_r}))
        return out
