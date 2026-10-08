# GOLD_AI — AI Shadow Research

## Preserved baseline
The exact pre-AI main branch is frozen at branch `baseline-pre-ai-2026-10-08`.
The six original positive-baseline strategy files are unchanged. Liquidity Sweep,
Power of Three and standalone Price Action are excluded from the active registry.
No previous backtest numbers are independently validated by this AI change.

## Run on Windows (CMD)
```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && git pull origin main && .venv\Scripts\python -m pip install -r requirements.txt && .venv\Scripts\python main.py
```

Optional Gemini setup: create a local `.env` file (never commit it):
```env
GEMINI_API_KEY=YOUR_KEY_HERE
GEMINI_MODEL=gemini-2.5-flash
```
Without a key, the AI logs NOT_EVALUATED and deterministic strategy scans still work.
Each current setup gets an independent model review recorded in
`Reports/ai_shadow_decisions.jsonl` with signal details, recent candles,
AI verdict, confidence, errors and timestamp. AI results never change signals.

**Important:** `main.py` is a one-shot market scan and report. It does NOT
place demo or live MT5 orders and is not a persistent scheduled service.
There is no broker execution adapter, deduplicated ongoing polling loop,
reconciliation, spread/slippage validation or risk enforcement yet.
Do not assume demo trading is enabled. The two-position limit is a paused
research assumption, not a live-trading configuration.

## Evaluation
Compare the same time-stamped deterministic setups with and without AI
judgment using held-out data. Log AI errors separately; do not count an
unavailable AI response as a rejected trade. AI confidence is not calibrated.
