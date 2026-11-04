# AGORA ZION TRADER (AZT)

The November 4 Admin build is `dist_rebuild_20261104/AZT_Admin.exe`. It integrates standalone startup, the frozen signal engine dependency fix, broker-time history recovery, refreshed P&L cards and the optional 30-day distributor trial. The matching Client repository provides both the standard and trial EXEs.

Admin uses an explicitly configured owner directory or database first. Otherwise it discovers an existing checkout database or uses `%LOCALAPPDATA%\GOLD_AI`. Keep the Admin EXE in its checkout to use the source Telegram workers. A standalone copy can run the bundled workers. From the owner checkout, run `& '.\.venv\Scripts\python.exe' -m server.telegram_admin reload` after editing Telegram source. Use `--root` when the running Admin uses a custom data directory.

To issue a distributor trial, select a PC Client in Admin and choose **Issue 30-Day Trial**. The first valid MT5 pairing starts the 30 days on the owner server's UTC clock. **Convert Trial** lets the client use a separately approved paid subscription. See [TELEGRAM_UPDATE.md](TELEGRAM_UPDATE.md) for the Telegram presentation work and [AZT_RELEASE.md](AZT_RELEASE.md) for the underlying application features and migration.

## Research and legacy tooling

Python-first XAUUSD multi-strategy scalping research system with nine independent M5 entry models.

## Fast historical research
The replay engine now limits each strategy evaluation to a 250-bar research window instead of repeatedly copying the entire history. Current active models require at most 80 explicit lookback bars; the larger window preserves warm-up for ATR and pivots while removing the main long-history slowdown.

Cash reporting is explicit and configurable. Default research assumptions are a 10,000 USD starting balance and 0.9% of current balance risked per signal. These are simulation assumptions, not the balance of the original R-only baseline.

Run:
```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && git pull origin main && .venv\Scripts\python backtest.py --bars 20000 --balance 10000 --risk 0.9
```

Reports: backtest_trades.csv, backtest_summary.csv, and backtest_equity.csv. Baseline 001 is preserved in Docs/FIRST_1000_BAR_BASELINE.md.

Combined-strategy cash equity currently processes signals sequentially and does not enforce a maximum simultaneous exposure rule; treat it as research equity, not an executable portfolio result. Live trading and AI intervention remain disabled.
