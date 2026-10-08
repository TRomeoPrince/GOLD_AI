# GOLD_AI

Python-first XAUUSD trading research and execution system.

## Phase 1
- Connect to the local MetaTrader 5 terminal from Python
- Auto-detect an available XAUUSD symbol (including broker suffixes such as .c/.m)
- Read account information
- Pull M5 and M15 candles
- Save diagnostics and market snapshots under `Reports/`
- Keep AI in SHADOW mode initially
- Do not place live trades yet

## Windows project path

`C:\Users\USER\Desktop\Bots\Forex\AMD1`

## Quick start

```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && python -m venv .venv && .venv\Scripts\python -m pip install -r requirements.txt
```

Then start MT5 and run:

```cmd
cd /d "C:\Users\USER\Desktop\Bots\Forex\AMD1" && .venv\Scripts\python main.py
```

The program currently performs diagnostics only. Trading execution will be added after the data connection and reporting layer are verified.
