from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = PROJECT_ROOT / "Reports"
DATA_DIR = PROJECT_ROOT / "data"

# Active demo markets. Broker suffixes/prefixes are resolved automatically.
ACTIVE_MARKETS = {
    "GOLD": "XAUUSD",
    "US30": "US30",
}

M5_BARS = 1000
M15_BARS = 300
MIN_STRATEGY_TIMEFRAME = "M5"

AI_MODE = "SHADOW"
LIVE_TRADING = False

# Demo execution only. Real accounts remain hard-blocked in demo_bot.py.
DEMO_RISK_PCT = 0.9
DEMO_POLL_SECONDS = 5
DEMO_MAX_SIGNAL_AGE_MINUTES = 10
DEMO_MAGIC = 560090

# No daily profit/loss cap for the current research phase.
DAILY_LOSS_CAP_PCT = None
DAILY_PROFIT_CAP_PCT = None

# Refined v1 risk geometry.
MIN_STOP_ATR = 1.5
