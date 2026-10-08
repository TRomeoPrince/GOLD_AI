from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import math
import pandas as pd
from strategies import StrategyRegistry

class BacktestEngine:
    def __init__(self, reports_dir: Path, warmup_bars: int = 100, max_hold_bars: int = 60):
        self.reports_dir=reports_dir; self.warmup_bars=warmup_bars; self.max_hold_bars=max_hold_bars
        self.reports_dir.mkdir(parents=True,exist_ok=True)

    def _resolve(self, signal, future):
        entry=float(signal.entry); sl=float(signal.stop_loss); tp=float(signal.take_profit)
        risk=abs(entry-sl)
        if risk<=0:return None
        mfe=0.0; mae=0.0
        for held,(_,bar) in enumerate(future.iterrows(),start=1):
            hi=float(bar.high); lo=float(bar.low)
            if signal.direction=="BUY":
                mfe=max(mfe,(hi-entry)/risk); mae=max(mae,(entry-lo)/risk)
                hit_sl=lo<=sl; hit_tp=hi>=tp
            else:
                mfe=max(mfe,(entry-lo)/risk); mae=max(mae,(hi-entry)/risk)
                hit_sl=hi>=sl; hit_tp=lo<=tp
            # With OHLC bars, intrabar ordering is unknowable if both are touched.
            # Resolve conservatively as SL.
            if hit_sl and hit_tp:return "SL",-1.0,held,mfe,mae,"BOTH_TOUCHED_SL_FIRST"
            if hit_sl:return "SL",-1.0,held,mfe,mae,"SL"
            if hit_tp:
                r=abs(tp-entry)/risk
                return "TP",r,held,mfe,mae,"TP"
            if held>=self.max_hold_bars:break
        if len(future)==0:return None
        exit_price=float(future.iloc[min(len(future),self.max_hold_bars)-1].close)
        r=(exit_price-entry)/risk if signal.direction=="BUY" else (entry-exit_price)/risk
        return "TIME",r,min(len(future),self.max_hold_bars),mfe,mae,"MAX_HOLD"

    def run(self, candles: pd.DataFrame):
        registry=StrategyRegistry(); rows=[]; seen=set()
        # At index i, the slice includes candle i as the current forming candle.
        # Strategies deliberately ignore their final row, so the setup is based
        # only on completed candles through i-1. Entry is signal.entry.
        for i in range(self.warmup_bars, len(candles)-2):
            history=candles.iloc[:i+1].copy()
            signals=registry.scan(history)
            for s in signals:
                key=(s.strategy_id,s.direction,s.setup_time)
                if key in seen:continue
                seen.add(key)
                outcome=self._resolve(s,candles.iloc[i:i+1+self.max_hold_bars])
                if outcome is None:continue
                exit_type,r_mult,bars_held,mfe,mae,exit_reason=outcome
                row=asdict(s); row["features"]=repr(row["features"])
                row.update({"exit_type":exit_type,"r_multiple":r_mult,"bars_held":bars_held,
                            "mfe_r":mfe,"mae_r":mae,"exit_reason":exit_reason})
                rows.append(row)
        trades=pd.DataFrame(rows)
        trades.to_csv(self.reports_dir/"backtest_trades.csv",index=False)
        summary=self._summary(trades)
        summary.to_csv(self.reports_dir/"backtest_summary.csv",index=False)
        return trades,summary

    def _summary(self,trades):
        cols=["strategy_id","trades","wins","losses","win_rate_pct","net_r","avg_r","profit_factor","max_drawdown_r"]
        if trades.empty:return pd.DataFrame(columns=cols)
        rows=[]
        for sid,g in trades.groupby("strategy_id"):
            rs=g.r_multiple.astype(float); wins=int((rs>0).sum()); losses=int((rs<0).sum())
            gross_win=float(rs[rs>0].sum()); gross_loss=abs(float(rs[rs<0].sum()))
            equity=rs.cumsum(); peaks=equity.cummax(); dd=equity-peaks
            rows.append({"strategy_id":sid,"trades":len(g),"wins":wins,"losses":losses,
                         "win_rate_pct":100*wins/len(g),"net_r":float(rs.sum()),"avg_r":float(rs.mean()),
                         "profit_factor":gross_win/gross_loss if gross_loss else math.inf,
                         "max_drawdown_r":abs(float(dd.min())) if len(dd) else 0.0})
        return pd.DataFrame(rows).sort_values("net_r",ascending=False)
