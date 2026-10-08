# GOLD_AI

Python-first XAUUSD multi-strategy scalping research system.

Strategies are **independent entry models**. A Market Structure trade does not require Support/Resistance or Range Break agreement, and vice versa.

## Current state

- MT5 Python market-data connection: working
- XAUUSD broker-symbol discovery: working
- M5 data collection: working
- Market Structure model: **ACTIVE**
- Support / Resistance model: rule extraction pending
- Range Break model: rule extraction pending
- AI: SHADOW architecture
- Live execution: disabled during research

The first active model uses HH/HL and LL/LH structure with M5 pullback/continuation entries. See `Docs/STRATEGY_RULES.md` for the distinction between source-supported concepts and engineering parameters.

## Run

```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && git pull origin main && .venv\Scripts\python main.py
```
