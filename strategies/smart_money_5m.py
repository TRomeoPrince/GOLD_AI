from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class SmartMoney5MStrategy(StrategyModel):
    """5-minute supply/demand displacement, fresh-zone retest model."""
    strategy_id="SMART_MONEY_5M"

    def __init__(self, search_bars=35, displacement_atr=1.0, max_base_bars=3,
                 stop_atr=0.15, reward_r=2.0):
        self.search_bars=search_bars; self.displacement_atr=displacement_atr
        self.max_base_bars=max_base_bars; self.stop_atr=stop_atr; self.reward_r=reward_r

    def scan(self,candles):
        if candles is None or len(candles)<60:return []
        f=candles.iloc[:-1].tail(self.search_bars+20).copy().reset_index(drop=True)
        f["atr"]=atr(f,14); last=f.iloc[-1]
        out=[]
        # Find the most recent strong departure. The candle immediately before
        # departure is the research approximation of the source's base/zone.
        for i in range(len(f)-3, 15, -1):
            d=f.iloc[i]; a=float(d.atr) if pd.notna(d.atr) else 0.0
            if a<=0:continue
            body=abs(float(d.close)-float(d.open))
            if body < self.displacement_atr*a:continue
            base=f.iloc[i-1]
            zone_lo=float(base.low); zone_hi=float(base.high)
            # Freshness: no completed candle between departure and current retest
            # may have already traded through the zone.
            middle=f.iloc[i+1:-1]
            previously_touched=((middle.low<=zone_hi)&(middle.high>=zone_lo)).any() if len(middle) else False
            if previously_touched:continue
            c=float(last.close); o=float(last.open); h=float(last.high); l=float(last.low)
            if float(d.close)>float(d.open):
                broke=float(d.close)>float(f.iloc[max(0,i-8):i].high.max())
                touched=l<=zone_hi and h>=zone_lo
                confirm=touched and c>o and c>zone_lo
                if broke and confirm:
                    entry=c; sl=zone_lo-self.stop_atr*a; risk=entry-sl
                    if risk>0: out.append(StrategySignal(self.strategy_id,"BUY","M5",str(last.time),entry,sl,entry+self.reward_r*risk,
                        "FRESH_DEMAND_ZONE_RETEST",{"zone_low":zone_lo,"zone_high":zone_hi,"displacement_atr":body/a,"reward_r":self.reward_r}))
                break
            else:
                broke=float(d.close)<float(f.iloc[max(0,i-8):i].low.min())
                touched=h>=zone_lo and l<=zone_hi
                confirm=touched and c<o and c<zone_hi
                if broke and confirm:
                    entry=c; sl=zone_hi+self.stop_atr*a; risk=sl-entry
                    if risk>0: out.append(StrategySignal(self.strategy_id,"SELL","M5",str(last.time),entry,sl,entry-self.reward_r*risk,
                        "FRESH_SUPPLY_ZONE_RETEST",{"zone_low":zone_lo,"zone_high":zone_hi,"displacement_atr":body/a,"reward_r":self.reward_r}))
                break
        return out
