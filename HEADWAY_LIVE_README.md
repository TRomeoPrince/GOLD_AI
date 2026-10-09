# GOLD_AI Headway micro live experiment

**Preserved baseline:** branch `backup-pre-headway-live-2026-10-09`.

This is an isolated live experiment. The six strategy modules, `demo_bot.py`,
and the demo-only executor have not been changed. The experiment does not
change the strategies' technical stop-loss or take-profit prices.

## Safety design

- Live orders require **all three**: `--live`, `HEADWAY_LIVE_ENABLED=YES`,
  and `HEADWAY_LIVE_ACCOUNT` matching the connected MT5 login.
- MT5 account must be REAL, Headway server, USD account currency.
- The broker's **minimum lot** is used. It is never increased to use a risk allowance.
- Loss at the original strategy stop is estimated with `mt5.order_calc_profit`.
- Risk estimate including a 10% cushion must not exceed the lower of **$5**
  and **50% of current equity**. Otherwise the signal is skipped.
- The 10% cushion is not a guarantee: gaps, slippage, fees, or stop-outs
  can cause a loss exceeding $5.
- Max one position **across the entire MT5 account**. Existing manual
  positions and pending orders block new entries.
- Minimum-lot margin must use at most 80% of free margin.
- Spread must be no more than $0.60 in gold price units at decision time.
- Realized P/L from this runner's magic number is checked daily (UTC);
  after -$5 it stops new entries for the rest of the day.
- Persistent per-account signal ledger prevents the same setup being
  re-executed after a restart. It records the setup before sending.
- A local Windows lock prevents a second runner instance on the same PC.
- Telegram notifications are optional; never run the same Telegram bot
  concurrently in `demo_bot.py` and `headway_live_bot.py`.
- `/pause` blocks new entries only. `/stop` stops Python but **does not
  close any existing MT5 position**.

## Check first (never places an order)

```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && git pull origin main && .venv\Scripts\python -m compileall -q headway_live_bot.py broker\headway_live_executor.py && .venv\Scripts\python headway_live_bot.py --check
```

## Explicit live opt-in (ONLY after reviewing the account and risk)

Replace `YOUR_MT5_LOGIN` with the account login printed by `--check`:

```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && set "HEADWAY_LIVE_ACCOUNT=YOUR_MT5_LOGIN" && set "HEADWAY_LIVE_ENABLED=YES" && .venv\Scripts\python headway_live_bot.py --live
```

Use `set` only in the intended CMD session. Close that window to clear
the session's opt-in values. Do not set these values globally with `setx`.

## Roll back to the pre-Headway code

The backup is a Git branch. Do not switch branches while a trading runner
is active. To inspect it without changing your working directory, open
the backup branch on GitHub. Do not overwrite local Reports/data or your
.env file when switching or restoring.
