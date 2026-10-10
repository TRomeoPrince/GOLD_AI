from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = PROJECT_ROOT / "Reports"
DATA_DIR = PROJECT_ROOT / "data"

SYMBOL_HINT = "XAUUSD"

# Current strategy direction is M15 Sweep & Flip only.
# Current explicitly confirmed deployment/research markets:
# Gold + US30 only. Override with GOLD_AI_MARKETS if needed.
MARKET_HINTS = {
    "XAUUSD": "XAUUSD",
    "GOLD": "XAUUSD",
    "US30": "US30",
    "XAGUSD": "XAGUSD",
    "SILVER": "XAGUSD",
    "BTCUSD": "BTCUSD",
    "NASDAQ": "NASDAQ",
}

def _active_markets_from_env() -> dict[str, str]:
    raw = os.getenv("GOLD_AI_MARKETS", "GOLD,US30").strip()
    if not raw:
        return {}
    out: dict[str, str] = {}
    for token in raw.split(","):
        key = token.strip().upper()
        if not key:
            continue
        out[key] = MARKET_HINTS.get(key, key)
    return out

ACTIVE_MARKETS = _active_markets_from_env()

M5_BARS = 1500
M15_BARS = 500
MIN_STRATEGY_TIMEFRAME = "M15"

AI_MODE = "SHADOW"
AI_PROVIDER = os.getenv("GOLD_AI_AI_PROVIDER", "GROQ").upper()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
LIVE_TRADING = False

# Configurable risk. Current project rule: allowed range 0.1% to 2.0%.
DEMO_RISK_PCT = float(os.getenv("GOLD_AI_RISK_PCT", "0.9"))
if not 0.1 <= DEMO_RISK_PCT <= 2.0:
    raise ValueError("GOLD_AI_RISK_PCT must be between 0.1 and 2.0 percent.")

DEMO_POLL_SECONDS = 5
DEMO_MAX_SIGNAL_AGE_MINUTES = 20
DEMO_MAGIC = 560090

# Portfolio risk guard remains infrastructure, not a daily cap.
MAX_TOTAL_OPEN_RISK_PCT = float(os.getenv("GOLD_AI_MAX_OPEN_RISK_PCT", "1.8"))

# Research experiments only: not enabled unless explicitly changed.
DAILY_LOSS_CAP_PCT = None
DAILY_PROFIT_CAP_PCT = None

# Exact video/session clock boundaries were not recoverable from the sync handoff.
# They MUST be supplied in broker-data time; no silent defaults are used.
def _optional_hour(name: str):
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None

ASIAN_START_HOUR = _optional_hour("GOLD_AI_ASIAN_START_HOUR")
ASIAN_END_HOUR = _optional_hour("GOLD_AI_ASIAN_END_HOUR")
LONDON_START_HOUR = _optional_hour("GOLD_AI_LONDON_START_HOUR")
LONDON_END_HOUR = _optional_hour("GOLD_AI_LONDON_END_HOUR")

M15_MIN_REWARD_R = 2.0
M15_H1_PIVOT_SPAN = 2
M15_STOP_BUFFER_FRACTION = 0.0

# Structure-based trailing confirmed in the latest bot work.
M15_TRAILING_ENABLED = True
M15_TRAIL_ACTIVATE_R = 1.0
M15_TRAIL_SWING_SPAN = 2
M15_TRAIL_ATR_BUFFER = 0.15
M15_TRAIL_LOOKBACK_BARS = 120
