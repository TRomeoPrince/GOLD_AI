from __future__ import annotations
import argparse
import MetaTrader5 as mt5
from broker.mt5_client import MT5Client
from backtesting import BacktestEngine
from config import REPORTS_DIR, SYMBOL_HINT

def main():
    p=argparse.ArgumentParser(description="GOLD_AI historical M5 strategy scanner/backtester")
    p.add_argument("--bars",type=int,default=20000)
    p.add_argument("--max-hold",type=int,default=60)
    args=p.parse_args()
    client=MT5Client(SYMBOL_HINT)
    try:
        status=client.connect()
        data=client.candles(mt5.TIMEFRAME_M5,args.bars)
        engine=BacktestEngine(REPORTS_DIR,max_hold_bars=args.max_hold)
        trades,summary=engine.run(data)
        print("GOLD_AI Historical M5 Backtest")
        print(f"Account : {status.account_login} @ {status.account_server}")
        print(f"Symbol  : {client.symbol}")
        print(f"Bars    : {len(data)}")
        print(f"Trades  : {len(trades)}")
        print(f"Reports : {REPORTS_DIR}")
        if summary.empty: print("No historical signals found.")
        else: print("\n"+summary.to_string(index=False))
        print("\nCreated: backtest_trades.csv, backtest_summary.csv")
        print("LIVE TRADING: DISABLED")
    finally:
        client.shutdown()
if __name__=="__main__": main()
