# GOLD_AI

Python-first XAUUSD multi-strategy scalping research system.

Nine independent M5 strategy models are active. Cross-strategy agreement is not required.

## Historical research

The historical scanner replays completed M5 candles through every strategy, de-duplicates signals, and resolves each setup against its own SL/TP. Results are measured in R so strategies with different stop sizes can be compared.

It writes:
- `Reports/backtest_trades.csv` — every historical setup and outcome, including MFE/MAE.
- `Reports/backtest_summary.csv` — trades, win rate, net/average R, profit factor and max drawdown per strategy.

If SL and TP are both touched inside the same M5 candle, OHLC data cannot reveal which happened first, so the backtester conservatively records the SL first. This avoids optimistic results.

### Run 20,000 M5 bars

```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && git pull origin main && .venv\Scripts\python backtest.py --bars 20000
```

Live execution and AI intervention remain disabled during research.
