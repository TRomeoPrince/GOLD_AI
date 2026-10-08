# GOLD_AI

Python-first XAUUSD multi-strategy scalping research and execution system.

## Architecture

Strategies are **independent entry models**. A valid setup does not require the other strategies to align. The registry scans every enabled model and records every valid signal separately.

Initial models:
- Market Structure
- Support / Resistance
- Range Break

M5 is the minimum strategy timeframe. Additional video-derived scalping models will be added as their exact rules are extracted and verified.

## Research policy

We do not assume cross-strategy confluence is required. Each strategy follows its own entry, invalidation, SL and TP rules. Overlapping signals are retained as separate research observations.

AI begins in SHADOW mode: it observes and scores setups but does not block or create trades.

Live trading remains disabled until strategy rules and risk/execution behavior are tested.

## Run

```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && git pull origin main && .venv\Scripts\python -m pip install -r requirements.txt && .venv\Scripts\python main.py
```
