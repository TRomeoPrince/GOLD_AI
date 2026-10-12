from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


def load_mt5_export(path: Path) -> pd.DataFrame:
    f = pd.read_csv(path, sep="\t")
    f.columns = [c.strip("<>") for c in f.columns]
    f["time"] = pd.to_datetime(f["DATE"] + " " + f["TIME"], format="%Y.%m.%d %H:%M:%S")
    return (
        f.rename(columns={"OPEN":"open","HIGH":"high","LOW":"low","CLOSE":"close","SPREAD":"spread"})
        [["time","open","high","low","close","spread"]]
        .sort_values("time").reset_index(drop=True)
    )


def atr(frame: pd.DataFrame, period: int = 14) -> np.ndarray:
    h=frame.high.to_numpy(float); l=frame.low.to_numpy(float); c=frame.close.to_numpy(float)
    pc=np.r_[np.nan,c[:-1]]
    tr=np.nanmax(np.vstack([h-l,np.abs(h-pc),np.abs(l-pc)]),axis=0)
    return pd.Series(tr).rolling(period).mean().to_numpy()


def complete_m15(m5: pd.DataFrame) -> pd.DataFrame:
    b=m5.set_index("time").resample("15min",label="right",closed="left").agg(
        open=("open","first"),high=("high","max"),low=("low","min"),
        close=("close","last"),count=("close","count"),
    )
    return b[b["count"]==3].drop(columns="count").dropna().reset_index()


def confirmed_swings(m5: pd.DataFrame, span: int = 2):
    h=m5.high.to_numpy(float); l=m5.low.to_numpy(float); n=len(m5)
    ph=np.zeros(n,dtype=bool); pl=np.zeros(n,dtype=bool)
    for i in range(span,n-span):
        ph[i]=h[i]>=h[i-span:i+span+1].max()
        pl[i]=l[i]<=l[i-span:i+span+1].min()
    latest_h=np.full(n,np.nan); latest_l=np.full(n,np.nan)
    sh=sl=np.nan
    for t in range(n):
        i=t-span
        if i>=span:
            if ph[i]: sh=h[i]
            if pl[i]: sl=l[i]
        latest_h[t]=sh; latest_l[t]=sl
    return latest_l, latest_h


class M15BreakoutBacktester:
    def __init__(
        self,
        trailing_enabled: bool,
        range_bars: int = 4,
        stop_buffer_atr: float = 0.15,
        reward_r: float = 2.0,
        max_hold_bars: int = 60,
        trail_activate_r: float = 1.0,
        trail_span: int = 2,
        trail_atr_buffer: float = 0.15,
        starting_balance: float = 10000.0,
        risk_pct: float = 0.9,
    ):
        self.trailing_enabled=trailing_enabled
        self.range_bars=range_bars
        self.stop_buffer_atr=stop_buffer_atr
        self.reward_r=reward_r
        self.max_hold_bars=max_hold_bars
        self.trail_activate_r=trail_activate_r
        self.trail_span=trail_span
        self.trail_atr_buffer=trail_atr_buffer
        self.starting_balance=starting_balance
        self.risk_pct=risk_pct

    def run_csv(self, path: Path, market: str):
        return self.run(load_mt5_export(path), market)

    def run(self, frame: pd.DataFrame, market: str):
        m5=frame.copy().reset_index(drop=True)
        m5["atr5"]=atr(m5)
        m15=complete_m15(m5)
        m15["atr15"]=atr(m15)
        times=m5.time.to_numpy("datetime64[ns]")
        mo=m5.open.to_numpy(float); mh=m5.high.to_numpy(float)
        ml=m5.low.to_numpy(float); mc=m5.close.to_numpy(float)
        ma=m5.atr5.to_numpy(float)
        latest_low,latest_high=confirmed_swings(m5,self.trail_span)
        rows=[]

        start=max(15+self.range_bars,self.range_bars+2)
        for j in range(start,len(m15)):
            bo=m15.iloc[j-1]; rt=m15.iloc[j]
            base=m15.iloc[j-1-self.range_bars:j-1]
            if len(base)!=self.range_bars or pd.isna(bo.atr15):
                continue

            a=float(bo.atr15); hi=float(base.high.max()); lo=float(base.low.min())
            direction=None
            if float(bo.close)>hi and float(bo.close)>float(bo.open):
                if float(rt.low)<=hi and float(rt.close)>hi and float(rt.close)>float(rt.open):
                    direction="BUY"; initial_sl=min(float(rt.low),hi)-self.stop_buffer_atr*a
            elif float(bo.close)<lo and float(bo.close)<float(bo.open):
                if float(rt.high)>=lo and float(rt.close)<lo and float(rt.close)<float(rt.open):
                    direction="SELL"; initial_sl=max(float(rt.high),lo)+self.stop_buffer_atr*a
            if direction is None:
                continue

            # Strict no-lookahead: retest is known only when the M15 closes;
            # execution begins at the next available M5 open.
            ts=pd.Timestamp(rt.time)
            entry_i=np.searchsorted(times,np.datetime64(ts),side="left")
            if entry_i>=len(m5):
                continue
            entry=float(mo[entry_i])
            risk=entry-initial_sl if direction=="BUY" else initial_sl-entry
            if risk<=0:
                continue
            tp=entry+self.reward_r*risk if direction=="BUY" else entry-self.reward_r*risk
            active_sl=initial_sl; mfe=mae=0.0; updates=0
            last=min(len(m5)-1,entry_i+self.max_hold_bars-1)

            for k in range(entry_i,last+1):
                high=float(mh[k]); low=float(ml[k]); close=float(mc[k])
                if direction=="BUY":
                    mfe=max(mfe,(high-entry)/risk); mae=max(mae,(entry-low)/risk)
                    hit_sl=low<=active_sl; hit_tp=high>=tp
                else:
                    mfe=max(mfe,(entry-low)/risk); mae=max(mae,(high-entry)/risk)
                    hit_sl=high>=active_sl; hit_tp=low<=tp

                if hit_sl:
                    exit_type="TRAIL_SL" if active_sl!=initial_sl else "SL"
                    exit_price=active_sl
                    r=(active_sl-entry)/risk if direction=="BUY" else (entry-active_sl)/risk
                    exit_i=k; break
                if hit_tp:
                    exit_type="TP"; exit_price=tp; r=self.reward_r; exit_i=k; break

                if self.trailing_enabled and mfe>=self.trail_activate_r and not np.isnan(ma[k]):
                    swing=latest_low[k] if direction=="BUY" else latest_high[k]
                    if not np.isnan(swing):
                        candidate=(swing-self.trail_atr_buffer*ma[k]
                                   if direction=="BUY"
                                   else swing+self.trail_atr_buffer*ma[k])
                        if direction=="BUY" and candidate>active_sl and candidate<close:
                            active_sl=float(candidate); updates+=1
                        elif direction=="SELL" and candidate<active_sl and candidate>close:
                            active_sl=float(candidate); updates+=1
            else:
                exit_i=last; exit_price=float(mc[last]); exit_type="TIME"
                r=(exit_price-entry)/risk if direction=="BUY" else (entry-exit_price)/risk

            rows.append({
                "market":market,"strategy_id":"M15_BREAKOUT","setup_time":ts,
                "entry_time":m5.time.iloc[entry_i],"exit_time":m5.time.iloc[exit_i],
                "direction":direction,"entry":entry,"initial_sl":initial_sl,"tp":tp,
                "exit_price":exit_price,"exit_type":exit_type,"r_multiple":float(r),
                "bars_held":exit_i-entry_i+1,"mfe_r":mfe,"mae_r":mae,
                "trail_updates":updates,
            })

        trades=pd.DataFrame(rows)
        return trades,self.summary(trades,market)

    def summary(self,trades:pd.DataFrame,market:str):
        if trades.empty:
            return {"market":market,"trailing":self.trailing_enabled,"trades":0}
        rs=trades.r_multiple.astype(float)
        wins=int((rs>0).sum()); losses=int((rs<0).sum()); bes=int((rs==0).sum())
        gw=float(rs[rs>0].sum()); gl=abs(float(rs[rs<0].sum()))
        pf=gw/gl if gl else math.inf
        eq=rs.cumsum(); mdd=abs(float((eq-eq.cummax()).min())); net=float(rs.sum())
        bal=self.starting_balance; peak=bal; cash_dd=0.0
        for r in rs:
            bal += bal*(self.risk_pct/100.0)*float(r)
            peak=max(peak,bal)
            cash_dd=max(cash_dd,100.0*(peak-bal)/peak)
        return {
            "market":market,"trailing":self.trailing_enabled,"trades":len(trades),
            "wins":wins,"losses":losses,"breakevens":bes,
            "win_rate_pct":100*wins/len(trades),"profit_factor":pf,
            "net_r":net,"avg_r":float(rs.mean()),"max_drawdown_r":mdd,
            "recovery_factor":net/mdd if mdd else math.inf,
            "starting_balance":self.starting_balance,"ending_balance":bal,
            "return_pct":100*(bal/self.starting_balance-1),
            "cash_max_dd_pct":cash_dd,
            "avg_duration_min":float(trades.bars_held.mean()*5),
            "avg_mfe_r":float(trades.mfe_r.mean()),
            "avg_mae_r":float(trades.mae_r.mean()),
            "trail_exit_pct":100*float((trades.exit_type=="TRAIL_SL").mean()),
        }
