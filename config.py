from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = PROJECT_ROOT / "Reports"
DATA_DIR = PROJECT_ROOT / "data"

# Legacy/default single-market hint retained for scanner/backtester compatibility.
SYMBOL_HINT = "XAUUSD"

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

# Shared portfolio exposure guard across Gold + US30.
# At 0.9% per trade this normally allows about two fully-risked positions.
MAX_TOTAL_OPEN_RISK_PCT = 1.8

# No daily profit/loss cap for the current research phase.
DAILY_LOSS_CAP_PCT = None
DAILY_PROFIT_CAP_PCT = None

# Refined v1 risk geometry.
MIN_STOP_ATR = 1.5


# M15_BREAKOUT structure trailing.
# Research experiments: this does not enable/disable any strategy by itself.
M15_TRAILING_ENABLED = True
M15_TRAIL_ACTIVATE_R = 1.0
M15_TRAIL_SWING_SPAN = 2
M15_TRAIL_ATR_BUFFER = 0.15
M15_TRAIL_LOOKBACK_BARS = 120
