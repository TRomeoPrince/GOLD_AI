# GOLD_AI

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
