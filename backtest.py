from __future__ import annotations
import argparse
import pandas as pd
import MetaTrader5 as mt5
from broker.mt5_client import MT5Client
from backtesting import BacktestEngine
from config import REPORTS_DIR, SYMBOL_HINT

def main():
    p=argparse.ArgumentParser(description="GOLD_AI fast historical M5 strategy backtester")
    p.add_argument("--bars",type=int,default=20000); p.add_argument("--max-hold",type=int,default=60)
    p.add_argument("--balance",type=float,default=10000.0); p.add_argument("--risk",type=float,default=0.9)
    args=p.parse_args(); client=MT5Client(SYMBOL_HINT)
    try:
        status=client.connect(); data=client.candles(mt5.TIMEFRAME_M5,args.bars)
        engine=BacktestEngine(REPORTS_DIR,max_hold_bars=args.max_hold,starting_balance=args.balance,risk_pct=args.risk)
        trades,summary,equity=engine.run(data); combined=engine.combined_summary(trades)
        print("GOLD_AI Fast Historical M5 Backtest")
        print(f"Account : {status.account_login} @ {status.account_server}\nSymbol  : {client.symbol}\nBars    : {len(data)}\nTrades  : {len(trades)}")
        print(f"Research balance: USD {args.balance:,.2f} | Risk/trade: {args.risk:.3g}%")
        if not summary.empty:
            cols=["strategy_id","trades","win_rate_pct","net_r","profit_factor","starting_balance","max_balance","min_balance","ending_balance","return_pct"]
            print("\nPER STRATEGY\n"+summary[cols].to_string(index=False,float_format=lambda x:f"{x:.2f}"))
            print("\nALL STRATEGIES COMBINED\n"+pd.DataFrame([combined])[cols].to_string(index=False,float_format=lambda x:f"{x:.2f}"))
        print(f"\nReports : {REPORTS_DIR}\nCreated: backtest_trades.csv, backtest_summary.csv, backtest_equity.csv")
        print("NOTE: cash simulation compounds a fixed % of current balance per signal. Combined mode is research-only and does not yet enforce concurrent-exposure limits.")
        print("LIVE TRADING: DISABLED")
    finally: client.shutdown()
if __name__=="__main__":main()
