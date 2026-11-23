from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class PullbackStrategy(StrategyModel):
    strategy_id="PULLBACK"
    def __init__(self, trend_bars=12, stop_atr=.2, reward_r=1.5,
                 min_trend_atr=.75, min_efficiency=.35):
        self.trend_bars=trend_bars; self.stop_atr=stop_atr; self.reward_r=reward_r
        # Starting research thresholds, not optimized live settings.
        self.min_trend_atr=float(min_trend_atr)
        self.min_efficiency=float(min_efficiency)
        if self.trend_bars < 2 or self.min_trend_atr < 0 or not 0 <= self.min_efficiency <= 1:
            raise ValueError("Invalid Pullback trend filter parameters")

    def _trend_direction(self, closes, current_atr):
        """Exclude flat and choppy windows instead of treating not-UP as DOWN."""
        net = float(closes.iloc[-1]) - float(closes.iloc[0])
        travel = float(closes.diff().abs().sum())
        if current_atr <= 0 or travel <= 0:
            return None
        efficiency = abs(net) / travel
        if abs(net) < self.min_trend_atr * current_atr or efficiency < self.min_efficiency:
            return None
        if net > 0:
            return "UP"
        if net < 0:
            return "DOWN"
        return None
    def scan(self,candles):
        if candles is None or len(candles)<40:return []
        f=candles.iloc[:-1].copy().reset_index(drop=True); f["atr"]=atr(f,14)
        last=f.iloc[-1]; a=float(last.atr) if pd.notna(last.atr) else 0
        if a<=0:return []
        w=f.iloc[-self.trend_bars-1:-1]; c=float(last.close); o=float(last.open)
        out=[]
        trend=self._trend_direction(w.close, a)
        rising=trend=="UP"; falling=trend=="DOWN"
        recent_low=float(w.low.tail(5).min()); recent_high=float(w.high.tail(5).max())
        if rising and float(last.low)<=recent_low+.25*a and c>o:
            sl=float(last.low)-self.stop_atr*a; r=c-sl
            if r>0: out.append(StrategySignal(self.strategy_id,"BUY","M5",str(last.time),c,sl,c+self.reward_r*r,"TREND_PULLBACK_CONTINUATION",{"trend":"UP","atr":a}))
        if falling and float(last.high)>=recent_high-.25*a and c<o:
            sl=float(last.high)+self.stop_atr*a; r=sl-c
            if r>0: out.append(StrategySignal(self.strategy_id,"SELL","M5",str(last.time),c,sl,c-self.reward_r*r,"TREND_PULLBACK_CONTINUATION",{"trend":"DOWN","atr":a}))
        return out
