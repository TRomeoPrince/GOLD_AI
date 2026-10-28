# AZT structure-break-candle trailing experiment

**Isolated research branch:** experiments/structure-break-candle-trailing, copied from main on 2026-10-28. Production Admin, Client, Telegram and live execution paths remain untouched. This runner makes NO MT5 orders.

## Source audit

- GOLD registry: SUPPORT_RESISTANCE, MARKET_STRUCTURE, PULLBACK, MOMENTUM_SCALP, M15_BREAKOUT.
- US30 registry: MARKET_STRUCTURE, PULLBACK, MOMENTUM_SCALP, M15_BREAKOUT.
- Each strategy owns its entry, initial SL, and TP.
- Existing backtesting/engine.py simulates fixed SL/TP; it does not simulate stop amendments.
- Existing broker/m15_trailing.py trails most recent confirmed M5 swing, activation 1R, for M15_BREAKOUT positions only. It is *not* the requested break-candle trailing.
- In the inspected source, personal_worker/hosted_executor and Client runtime/executor do not call the old M15 trailing manager.
- Existing risk, news lock, subscription, duplication and stale-signal safeguards remain unchanged.

## What the paired experiment compares

- FIXED: original SL and TP.
- BREAK_CANDLE: original SL and TP, but after a completed bullish BOS/CHoCH candidate or compact range breakout, trail just **below the break candle's LOW** minus ATR buffer. For a bearish break, trail just **above the break candle's HIGH** plus buffer.
- Breaks are recognized on fully completed M5, M15, and H1 candles (not direction-dependent timeframes). A confirmed pivot must have enough subsequent bars *already closed* before it can qualify; a consolidation breakout must body-close beyond its prior range.
- Stops only tighten and are only applied from the NEXT M5 candle after the break has closed. An optional minimum profit activation is given by --activate-r (default 0R; repeat with 1R).
- Same strategy signals, same next-bar opening entry, no future price leakage to entry scanners.
- Conservative same-bar TP/SL handling: if both hit, SL wins; stop gaps fill at the opening price.
- Optional --cost-price is a fixed round-trip execution cost in the quote's price units, subtracted before R calculation. Zero means **GROSS**, not cost-adjusted.
- Starting balance and risk are scenario assumptions; return/drawdown reports approximate sequential compounding and do not reproduce the exact overlapping live portfolio.
- No broker stop-level, swaps, varying spread, slippage or order-rejection model yet. Validate before any live rollout.

## Run on your PC with actual historical candles

The GitHub repo contains a 1,000-bar baseline *summary*, but no raw OHLC dataset. Therefore there is no honest real new win-rate until historical candles are supplied.

Create an isolated Windows Git worktree while retaining your current live version:

~~~cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && git fetch origin && git worktree add -b azt-structure-trail-local "..\AMD1_STRUCTURE_TRAIL_RESEARCH" origin/experiments/structure-break-candle-trailing
~~~

Ensure your intended MT5 terminal is open and has M5 history. Read-only backtest:

~~~cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1_STRUCTURE_TRAIL_RESEARCH" && "C:\Users\USER\Desktop\Bots\Forex\AMD1\.venv\Scripts\python.exe" -m research.structure_break_experiment --mt5-bars 10000 --market GOLD --symbol XAUUSD --balance 1000 --risk-pct 0.9 --activate-r 0 --buffer-atr 0.15 --output Reports\structure_break_trail
~~~

Repeat with --activate-r 1 --output Reports\structure_break_trail_1R to compare trailing activation sensitivities.

Alternatively pass --csv path\to\UTC_M5_OHLC.csv instead of --mt5-bars; required fields: time,open,high,low,close in true UTC.

Reports: paired_trades.csv, paired_deltas.csv, summary.csv. Compare by strategy, win-rate, Net R, profit factor, return %, max drawdown and trail updates. Do not interpret test fixtures as a historical performance result.

This script uses MT5Client for candles and clock normalization, and never calls order_send.
