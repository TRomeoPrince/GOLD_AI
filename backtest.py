from __future__ import annotations

import argparse
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

from broker.mt5_client import MT5Client
from config import REPORTS_DIR, SYMBOL_HINT
from research.sweep_flip_backtester import SweepFlipBacktester


def main() -> None:
    p = argparse.ArgumentParser(
        description="GOLD_AI strict no-lookahead M15 Sweep & Flip MT5 backtester"
    )
    p.add_argument("--bars", type=int, default=50000)
    p.add_argument("--symbol", default=SYMBOL_HINT)
    p.add_argument("--market", default="MARKET")
    p.add_argument("--asian-start", type=int, required=True)
    p.add_argument("--asian-end", type=int, required=True)
    p.add_argument("--london-start", type=int, required=True)
    p.add_argument("--london-end", type=int, required=True)
    p.add_argument("--balance", type=float, default=10000.0)
    p.add_argument("--risk", type=float, default=0.9)
    args = p.parse_args()

    if not 0.1 <= args.risk <= 2.0:
        raise SystemExit("--risk must be between 0.1 and 2.0 percent.")

    client = MT5Client(args.symbol)
    try:
        status = client.connect()
        data = client.candles(mt5.TIMEFRAME_M5, args.bars)
        tester = SweepFlipBacktester(
            asian_start_hour=args.asian_start,
            asian_end_hour=args.asian_end,
            london_start_hour=args.london_start,
            london_end_hour=args.london_end,
            starting_balance=args.balance,
            risk_pct=args.risk,
        )
        trades, summary = tester.run(data, args.market)
        out = Path(REPORTS_DIR) / "sweep_flip"
        out.mkdir(parents=True, exist_ok=True)
        trades.to_csv(out / f"{args.market}_trades.csv", index=False)
        pd.DataFrame([summary]).to_csv(out / f"{args.market}_summary.csv", index=False)

        print("GOLD_AI M15 SWEEP & FLIP — STRICT NO-LOOKAHEAD")
        print(f"Account : {status.account_login} @ {status.account_server}")
        print(f"Symbol  : {client.symbol}")
        print(f"Bars    : {len(data)}")
        print(
            f"Sessions: Asian {args.asian_start:02d}:00-{args.asian_end:02d}:00 | "
            f"London {args.london_start:02d}:00-{args.london_end:02d}:00 "
            "(MT5 candle timezone)"
        )
        print(pd.DataFrame([summary]).to_string(index=False))
        print(f"Reports : {out}")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
