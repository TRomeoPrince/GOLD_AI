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
