from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from research.sweep_flip_backtester import SweepFlipBacktester


def main() -> None:
    p = argparse.ArgumentParser(
        description="Strict no-lookahead M15 Sweep & Flip CSV backtester"
    )
    p.add_argument("csv", help="MT5 M5 export (tab-separated)")
    p.add_argument("--market", default="MARKET")
    p.add_argument("--asian-start", type=int, required=True)
    p.add_argument("--asian-end", type=int, required=True)
    p.add_argument("--london-start", type=int, required=True)
    p.add_argument("--london-end", type=int, required=True)
    p.add_argument("--risk", type=float, default=0.9)
    p.add_argument("--balance", type=float, default=10000.0)
    p.add_argument("--out", default="Reports/sweep_flip")
    args = p.parse_args()

    if not 0.1 <= args.risk <= 2.0:
        raise SystemExit("--risk must be between 0.1 and 2.0")

    tester = SweepFlipBacktester(
        asian_start_hour=args.asian_start,
        asian_end_hour=args.asian_end,
        london_start_hour=args.london_start,
        london_end_hour=args.london_end,
        risk_pct=args.risk,
        starting_balance=args.balance,
    )
    trades, summary = tester.run_csv(Path(args.csv), market=args.market)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out / f"{args.market}_trades.csv", index=False)
    pd.DataFrame([summary]).to_csv(out / f"{args.market}_summary.csv", index=False)

    print(pd.DataFrame([summary]).to_string(index=False))
    print(f"Reports: {out}")


if __name__ == "__main__":
    main()
