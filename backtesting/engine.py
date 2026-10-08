from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import math
import pandas as pd
from strategies import StrategyRegistry

class BacktestEngine:
    def __init__(self,reports_dir:Path,warmup_bars=100,max_hold_bars=60,history_window=250,starting_balance=10000.0,risk_pct=0.9):
        self.reports_dir=reports_dir; self.warmup_bars=warmup_bars; self.max_hold_bars=max_hold_bars
        self.history_window=history_window; self.starting_balance=float(starting_balance); self.risk_pct=float(risk_pct)
        self.reports_dir.mkdir(parents=True,exist_ok=True)

    def _resolve(self,s,future):
        entry=float(s.entry); sl=float(s.stop_loss); tp=float(s.take_profit); risk=abs(entry-sl)
        if risk<=0:return None
        mfe=mae=0.0
        for held,(_,b) in enumerate(future.iterrows(),1):
            hi=float(b.high); lo=float(b.low)
            if s.direction=="BUY": mfe=max(mfe,(hi-entry)/risk); mae=max(mae,(entry-lo)/risk); hit_sl=lo<=sl; hit_tp=hi>=tp
            else: mfe=max(mfe,(entry-lo)/risk); mae=max(mae,(hi-entry)/risk); hit_sl=hi>=sl; hit_tp=lo<=tp
            if hit_sl and hit_tp:return "SL",-1.0,held,mfe,mae,"BOTH_TOUCHED_SL_FIRST"
            if hit_sl:return "SL",-1.0,held,mfe,mae,"SL"
            if hit_tp:return "TP",abs(tp-entry)/risk,held,mfe,mae,"TP"
            if held>=self.max_hold_bars:break
        if future.empty:return None
        b=future.iloc[min(len(future),self.max_hold_bars)-1]; px=float(b.close)
        r=(px-entry)/risk if s.direction=="BUY" else (entry-px)/risk
        return "TIME",r,min(len(future),self.max_hold_bars),mfe,mae,"MAX_HOLD"

    def run(self,candles:pd.DataFrame):
        registry=StrategyRegistry(); rows=[]; seen=set()
        for i in range(self.warmup_bars,len(candles)-2):
            start=max(0,i-self.history_window)
            history=candles.iloc[start:i+1].copy()
            for s in registry.scan(history):
                key=(s.strategy_id,s.direction,s.setup_time)
                if key in seen:continue
                seen.add(key); outcome=self._resolve(s,candles.iloc[i:i+1+self.max_hold_bars])
                if outcome is None:continue
                exit_type,r_mult,bars_held,mfe,mae,exit_reason=outcome
                row=asdict(s); row["features"]=repr(row["features"])
                row.update({"exit_type":exit_type,"r_multiple":r_mult,"bars_held":bars_held,"mfe_r":mfe,"mae_r":mae,"exit_reason":exit_reason})
                rows.append(row)
        trades=pd.DataFrame(rows)
        if not trades.empty: trades=trades.sort_values(["setup_time","strategy_id"]).reset_index(drop=True)
        trades.to_csv(self.reports_dir/"backtest_trades.csv",index=False)
        summary=self._summary(trades); summary.to_csv(self.reports_dir/"backtest_summary.csv",index=False)
        equity=self._equity_reports(trades); equity.to_csv(self.reports_dir/"backtest_equity.csv",index=False)
        return trades,summary,equity

    def _stats(self,rs):
        rs=pd.Series(rs,dtype=float); wins=int((rs>0).sum()); losses=int((rs<0).sum())
        gw=float(rs[rs>0].sum()); gl=abs(float(rs[rs<0].sum())); eq=rs.cumsum(); dd=eq-eq.cummax()
        return wins,losses,gw/gl if gl else math.inf,abs(float(dd.min())) if len(dd) else 0.0

    def _balance_path(self,g):
        bal=self.starting_balance; maximum=minimum=bal; path=[]
        for _,r in g.iterrows():
            risk_cash=bal*(self.risk_pct/100.0); pnl=risk_cash*float(r.r_multiple); bal+=pnl
            maximum=max(maximum,bal); minimum=min(minimum,bal); path.append((bal,pnl,risk_cash))
        return bal,maximum,minimum,path

    def _summary(self,trades):
        cols=["strategy_id","trades","wins","losses","win_rate_pct","net_r","avg_r","profit_factor","max_drawdown_r","starting_balance","max_balance","min_balance","ending_balance","return_pct"]
        if trades.empty:return pd.DataFrame(columns=cols)
        rows=[]
        for sid,g in trades.groupby("strategy_id",sort=False):
            g=g.sort_values("setup_time"); rs=g.r_multiple.astype(float); wins,losses,pf,mdd=self._stats(rs); end,mx,mn,_=self._balance_path(g)
            rows.append({"strategy_id":sid,"trades":len(g),"wins":wins,"losses":losses,"win_rate_pct":100*wins/len(g),"net_r":float(rs.sum()),"avg_r":float(rs.mean()),"profit_factor":pf,"max_drawdown_r":mdd,"starting_balance":self.starting_balance,"max_balance":mx,"min_balance":mn,"ending_balance":end,"return_pct":100*(end/self.starting_balance-1)})
        return pd.DataFrame(rows).sort_values("net_r",ascending=False)

    def _equity_reports(self,trades):
        if trades.empty:return pd.DataFrame(columns=["portfolio","setup_time","strategy_id","r_multiple","risk_cash","pnl","balance"])
        out=[]; groups=[("ALL_STRATEGIES",trades.sort_values(["setup_time","strategy_id"]))]+[(sid,g.sort_values("setup_time")) for sid,g in trades.groupby("strategy_id")]
        for name,g in groups:
            _,_,_,path=self._balance_path(g)
            for (_,r),(bal,pnl,risk_cash) in zip(g.iterrows(),path):
                out.append({"portfolio":name,"setup_time":r.setup_time,"strategy_id":r.strategy_id,"r_multiple":r.r_multiple,"risk_cash":risk_cash,"pnl":pnl,"balance":bal})
        return pd.DataFrame(out)

    def combined_summary(self,trades):
        if trades.empty:return {}
        g=trades.sort_values(["setup_time","strategy_id"]); rs=g.r_multiple.astype(float); wins,losses,pf,mdd=self._stats(rs); end,mx,mn,_=self._balance_path(g)
        return {"strategy_id":"ALL_STRATEGIES","trades":len(g),"wins":wins,"losses":losses,"win_rate_pct":100*wins/len(g),"net_r":float(rs.sum()),"avg_r":float(rs.mean()),"profit_factor":pf,"max_drawdown_r":mdd,"starting_balance":self.starting_balance,"max_balance":mx,"min_balance":mn,"ending_balance":end,"return_pct":100*(end/self.starting_balance-1)}
