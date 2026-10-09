# GOLD_AI demo execution

Run only after MetaTrader 5 is logged into a **DEMO** account and Algo Trading is enabled.

```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && git pull origin main && .venv\Scripts\python demo_bot.py
```

Safety behavior:
- hard-blocks non-demo MT5 accounts using MT5 account trade mode
- XAUUSD only through the existing symbol resolver
- six frozen strategy models
- 0.9% of current equity risk target per trade
- duplicate signal protection during the running process
- skips stale setups older than 10 minutes
- skips setups whose current market price is already outside the original SL/TP geometry
- logs every order attempt to `Reports/demo_orders.jsonl`
- no 2-position concurrency limit in this experimental demo build
- opposing positions may coexist only when the broker/account is hedging-capable
- AI does not control demo execution

This is a demo-testing runner, not a live-account runner. Real accounts are rejected before the trading loop starts.
