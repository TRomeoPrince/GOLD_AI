from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = PROJECT_ROOT / "Reports"
DATA_DIR = PROJECT_ROOT / "data"

SYMBOL_HINT = "XAUUSD"
M5_BARS = 1000
M15_BARS = 300
MIN_STRATEGY_TIMEFRAME = "M5"

AI_MODE = "SHADOW"
LIVE_TRADING = False

# Demo execution only. Real accounts are hard-blocked in demo_bot.py.
DEMO_RISK_PCT = 0.9
DEMO_POLL_SECONDS = 5
DEMO_MAX_SIGNAL_AGE_MINUTES = 10
DEMO_MAGIC = 560090
