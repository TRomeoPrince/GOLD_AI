from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = PROJECT_ROOT / "Reports"
DATA_DIR = PROJECT_ROOT / "data"

SYMBOL_HINT = "XAUUSD"

# Current routing: Gold refined Support & Resistance + M15 Breakout; US30 M15 Breakout.
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

AI_MODE = os.getenv("GOLD_AI_AI_MODE", "OFF").upper()
AI_PROVIDER = os.getenv("GOLD_AI_AI_PROVIDER", "GROQ").upper()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
LIVE_TRADING = False

# Configurable risk. Current project rule: allowed range 0.1% to 2.0%.
DEMO_RISK_PCT = float(os.getenv("GOLD_AI_RISK_PCT", "0.9"))
if not 0.1 <= DEMO_RISK_PCT <= 2.0:
    raise ValueError("GOLD_AI_RISK_PCT must be between 0.1 and 2.0 percent.")

# Small-account minimum-lot adaptation.
# Normal sizing still targets DEMO_RISK_PCT. If that produces less than the
# broker minimum volume, the bot may use the broker minimum lot only when the
# resulting stop-loss risk stays below this hard percentage ceiling.
SMALL_ACCOUNT_MAX_RISK_PCT = float(
    os.getenv("GOLD_AI_SMALL_ACCOUNT_MAX_RISK_PCT", "15.0")
)
if not 0 < SMALL_ACCOUNT_MAX_RISK_PCT <= 100:
    raise ValueError("GOLD_AI_SMALL_ACCOUNT_MAX_RISK_PCT must be > 0 and <= 100.")

DEMO_POLL_SECONDS = 5
DEMO_MAX_SIGNAL_AGE_MINUTES = 20
DEMO_MAGIC = 560090

# Small-account live guardrail.
# Normal sizing still targets 0.9% per trade. If the broker minimum lot forces
# a larger position, one trade may use up to 15% effective risk, while total
# planned loss across all open GOLD_AI positions is capped at 40% of equity.
_raw_open_risk_cap = os.getenv("GOLD_AI_MAX_OPEN_RISK_PCT", "40.0").strip()
MAX_TOTAL_OPEN_RISK_PCT = float(_raw_open_risk_cap) if _raw_open_risk_cap else None
if MAX_TOTAL_OPEN_RISK_PCT is not None and MAX_TOTAL_OPEN_RISK_PCT <= 0:
    raise ValueError("GOLD_AI_MAX_OPEN_RISK_PCT must be positive when enabled.")

# Position count is not the primary guard. Risk is controlled by the portfolio
# open-risk cap, while profitable older positions can be protected and allow
# fresh entries. Set GOLD_AI_MAX_CONCURRENT_POSITIONS only if a hard count cap
# is explicitly desired.
_raw_max_positions = os.getenv("GOLD_AI_MAX_CONCURRENT_POSITIONS", "").strip()
MAX_CONCURRENT_POSITIONS = int(_raw_max_positions) if _raw_max_positions else None
if MAX_CONCURRENT_POSITIONS is not None and MAX_CONCURRENT_POSITIONS < 1:
    raise ValueError("GOLD_AI_MAX_CONCURRENT_POSITIONS must be at least 1 when enabled.")

# When a fresh same-direction position opens, older profitable positions are
# moved into a small locked-profit zone. For Gold, one pip is derived from the
# broker symbol digits/point size. Default is the middle of the requested
# 9-15 pip zone and can be tuned within that range.
STACK_PROFIT_LOCK_PIPS = float(os.getenv("GOLD_AI_STACK_PROFIT_LOCK_PIPS", "12"))
if not 9.0 <= STACK_PROFIT_LOCK_PIPS <= 15.0:
    raise ValueError("GOLD_AI_STACK_PROFIT_LOCK_PIPS must be between 9 and 15.")

# Research experiments only: not enabled unless explicitly changed.
DAILY_LOSS_CAP_PCT = None
DAILY_PROFIT_CAP_PCT = None

# Legacy Sweep & Flip session settings retained for research compatibility only.
# Active M15 Breakout routing does not require session boundaries.
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
