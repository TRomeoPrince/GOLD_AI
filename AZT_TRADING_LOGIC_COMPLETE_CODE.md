# AZT — Trading Logic Source Code for Gemini and Claude

> Source: private `TRomeoPrince/GOLD_AI` repository, commit `c0f7263742438a33fc1c9ba41dedfcfd972655fd`.

> Complete verbatim source for the ten files requested in the Gemini screenshot. This is a read-only code snapshot, **not** an implementation update. It does not include the Client repository or other Owner modules.

## File index

1. `strategies/registry.py` — Git blob `1f386cbd06b17cb617956df96a925f0cd19bcf8e`
2. `strategies/m15_breakout.py` — Git blob `fc1a1f916688ef674319b53396b58f3c8cdfe7f5`
3. `strategies/pullback.py` — Git blob `43afb788c3b908315c7407b16d4ddfbb31b71a34`
4. `strategies/market_structure.py` — Git blob `67de6b75712ff7613d10d6bf88cb9a9f4c10938e`
5. `strategies/support_resistance.py` — Git blob `02ff15afc77eb3c38c79f89b81fbfc9ed92c3a8e`
6. `strategies/momentum_scalp.py` — Git blob `afcdb5e35e506ebcae99e8de2130b191363b47a6`
7. `server/signal_engine.py` — Git blob `9d1e7da13ef5225c91c00bf4c89e69e4f2aa1ad3`
8. `broker/m15_trailing.py` — Git blob `12b5f7ed7a30212621c87a81c08ebddcf91d108e`
9. `backtesting/engine.py` — Git blob `3b2d70b4c67f58a736e55ca73773404883970acf`
10. `config.py` — Git blob `d901023c28cfa1efa094bd3fd002172c9984f8bd`

---
## 1. `strategies/registry.py`

Original Git blob: `1f386cbd06b17cb617956df96a925f0cd19bcf8e`

~~~python
from .m15_breakout import M15BreakoutStrategy
from .market_structure import MarketStructureStrategy
from .momentum_scalp import MomentumScalpStrategy
from .pullback import PullbackStrategy
from .support_resistance import SupportResistanceStrategy


class StrategyRegistry:
    """Current GOLD_AI market-specific routing.

    GOLD/XAUUSD:
      - refined Support & Resistance
      - Market Structure
      - Pullback
      - Momentum Scalp
      - M15 Breakout

    US30:
      - Market Structure
      - Pullback
      - Momentum Scalp
      - M15 Breakout

    Sweep & Flip remains disabled.

    Risk sizing is NOT controlled here. All active strategies continue through
    the shared executor, so the configured per-trade and portfolio risk guards
    remain unchanged.
    """

    def __init__(self, market: str | None = None, **strategy_kwargs):
        market_key = (market or "").upper()

        shared = [
            MarketStructureStrategy(),
            PullbackStrategy(),
            MomentumScalpStrategy(min_stop_atr=1.5),
            M15BreakoutStrategy(),
        ]

        if market_key in {"GOLD", "XAUUSD"}:
            self.models = [
                SupportResistanceStrategy(min_stop_atr=1.5),
                *shared,
            ]
        elif market_key in {"US30", "US30.CASH", "US30.STD"}:
            self.models = shared
        else:
            self.models = []

    def scan(self, candles):
        signals = []
        for model in self.models:
            signals.extend(model.scan(candles))
        return signals

    @property
    def strategy_ids(self):
        return [m.strategy_id for m in self.models]
~~~

---

## 2. `strategies/m15_breakout.py`

Original Git blob: `fc1a1f916688ef674319b53396b58f3c8cdfe7f5`

~~~python
from __future__ import annotations

import pandas as pd

from .base import StrategyModel, StrategySignal
from .indicators import atr


class M15BreakoutStrategy(StrategyModel):
    """Documented M15 breakout -> retest -> continuation model.

    This is the reproducible reconstruction of the previously researched
    S3_15M_BREAKOUT concept. The surviving project notes specify:
    - M15 body-close breakout of a local range/structure level;
    - breakout alone is insufficient;
    - require a retest that holds the broken level;
    - continuation confirmation before entry;
    - structural stop beyond the retest/broken level;
    - approximately 1:2 reward:risk.

    The old S3_15M_BREAKOUT source was not committed to the previous repos, so
    the numeric lookback/buffer below are explicit research parameters rather
    than claims about the original video.
    """

    strategy_id = "M15_BREAKOUT"

    def __init__(
        self,
        range_bars: int = 4,
        stop_buffer_atr: float = 0.15,
        reward_r: float = 2.0,
    ) -> None:
        self.range_bars = int(range_bars)
        self.stop_buffer_atr = float(stop_buffer_atr)
        self.reward_r = float(reward_r)

    @staticmethod
    def _m15_from_m5(candles: pd.DataFrame) -> pd.DataFrame:
        # Match the rest of GOLD_AI: never inspect the final/forming M5 candle.
        closed = candles.iloc[:-1].copy()
        if closed.empty:
            return pd.DataFrame()

        f = closed.set_index("time").sort_index()
        bars = f.resample("15min", label="right", closed="left").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            count=("close", "count"),
        )
        # A valid M15 candle must contain all three M5 bars.
        bars = bars[bars["count"] == 3].drop(columns="count").dropna().reset_index()
        if bars.empty:
            return bars
        bars["atr"] = atr(bars, 14)
        return bars

    def scan(self, candles) -> list[StrategySignal]:
        if candles is None or len(candles) < 90:
            return []

        m15 = self._m15_from_m5(candles)
        need = max(16, self.range_bars + 2)
        if len(m15) < need:
            return []

        # Breakout must be followed by a completed M15 retest/confirmation bar.
        breakout = m15.iloc[-2]
        retest = m15.iloc[-1]
        base = m15.iloc[-2 - self.range_bars:-2]

        a = float(breakout["atr"]) if pd.notna(breakout["atr"]) else 0.0
        if a <= 0 or len(base) != self.range_bars:
            return []

        range_high = float(base["high"].max())
        range_low = float(base["low"].min())

        bo_o = float(breakout["open"])
        bo_c = float(breakout["close"])
        rt_o = float(retest["open"])
        rt_h = float(retest["high"])
        rt_l = float(retest["low"])
        rt_c = float(retest["close"])

        out: list[StrategySignal] = []

        # Bullish: body closes above the prior local range, then the next M15
        # candle retests/holds the broken high and closes bullish above it.
        if bo_c > range_high and bo_c > bo_o:
            retest_holds = rt_l <= range_high and rt_c > range_high and rt_c > rt_o
            if retest_holds:
                entry = rt_c
                sl = min(rt_l, range_high) - self.stop_buffer_atr * a
                risk = entry - sl
                if risk > 0:
                    out.append(
                        StrategySignal(
                            self.strategy_id,
                            "BUY",
                            "M15",
                            str(retest["time"]),
                            entry,
                            sl,
                            entry + self.reward_r * risk,
                            "M15_RANGE_BREAK_RETEST_CONTINUATION",
                            {
                                "range_high": range_high,
                                "range_low": range_low,
                                "atr15": a,
                                "range_bars": self.range_bars,
                                "reward_r": self.reward_r,
                            },
                        )
                    )

        # Bearish mirror.
        if bo_c < range_low and bo_c < bo_o:
            retest_holds = rt_h >= range_low and rt_c < range_low and rt_c < rt_o
            if retest_holds:
                entry = rt_c
                sl = max(rt_h, range_low) + self.stop_buffer_atr * a
                risk = sl - entry
                if risk > 0:
                    out.append(
                        StrategySignal(
                            self.strategy_id,
                            "SELL",
                            "M15",
                            str(retest["time"]),
                            entry,
                            sl,
                            entry - self.reward_r * risk,
                            "M15_RANGE_BREAK_RETEST_CONTINUATION",
                            {
                                "range_high": range_high,
                                "range_low": range_low,
                                "atr15": a,
                                "range_bars": self.range_bars,
                                "reward_r": self.reward_r,
                            },
                        )
                    )

        return out
~~~

---

## 3. `strategies/pullback.py`

Original Git blob: `43afb788c3b908315c7407b16d4ddfbb31b71a34`

~~~python
from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr

class PullbackStrategy(StrategyModel):
    strategy_id="PULLBACK"
    def __init__(self, trend_bars=12, stop_atr=.2, reward_r=1.5):
        self.trend_bars=trend_bars; self.stop_atr=stop_atr; self.reward_r=reward_r
    def scan(self,candles):
        if candles is None or len(candles)<40:return []
        f=candles.iloc[:-1].copy().reset_index(drop=True); f["atr"]=atr(f,14)
        last=f.iloc[-1]; a=float(last.atr) if pd.notna(last.atr) else 0
        if a<=0:return []
        w=f.iloc[-self.trend_bars-1:-1]; c=float(last.close); o=float(last.open)
        out=[]
        rising=float(w.close.iloc[-1])>float(w.close.iloc[0]); falling=not rising
        recent_low=float(w.low.tail(5).min()); recent_high=float(w.high.tail(5).max())
        if rising and float(last.low)<=recent_low+.25*a and c>o:
            sl=float(last.low)-self.stop_atr*a; r=c-sl
            if r>0: out.append(StrategySignal(self.strategy_id,"BUY","M5",str(last.time),c,sl,c+self.reward_r*r,"TREND_PULLBACK_CONTINUATION",{"trend":"UP","atr":a}))
        if falling and float(last.high)>=recent_high-.25*a and c<o:
            sl=float(last.high)+self.stop_atr*a; r=sl-c
            if r>0: out.append(StrategySignal(self.strategy_id,"SELL","M5",str(last.time),c,sl,c-self.reward_r*r,"TREND_PULLBACK_CONTINUATION",{"trend":"DOWN","atr":a}))
        return out
~~~

---

## 4. `strategies/market_structure.py`

Original Git blob: `67de6b75712ff7613d10d6bf88cb9a9f4c10938e`

~~~python
from __future__ import annotations

import pandas as pd

from .base import StrategyModel, StrategySignal
from .indicators import atr


class MarketStructureStrategy(StrategyModel):
    """M5 market-structure entry model.

    Source-backed core:
    - bullish structure = higher highs + higher lows
    - bearish structure = lower lows + lower highs
    - entries are sought on a pullback into the latest structural swing area

    The numeric pivot/ATR tolerances are explicit bot operationalisation
    parameters so they can be measured and tuned; they are not claimed as
    quotations from the training video.
    """

    strategy_id = "MARKET_STRUCTURE"

    def __init__(
        self,
        pivot_span: int = 2,
        pullback_tolerance_atr: float = 0.20,
        stop_buffer_atr: float = 0.15,
        reward_r: float = 1.5,
    ) -> None:
        self.pivot_span = pivot_span
        self.pullback_tolerance_atr = pullback_tolerance_atr
        self.stop_buffer_atr = stop_buffer_atr
        self.reward_r = reward_r

    def _pivots(self, frame: pd.DataFrame):
        highs, lows = [], []
        span = self.pivot_span
        for i in range(span, len(frame) - span):
            h = frame.iloc[i]["high"]
            l = frame.iloc[i]["low"]
            window = frame.iloc[i - span : i + span + 1]
            if h >= window["high"].max():
                highs.append((i, float(h)))
            if l <= window["low"].min():
                lows.append((i, float(l)))
        return highs, lows

    def scan(self, candles) -> list[StrategySignal]:
        if candles is None or len(candles) < 40:
            return []

        frame = candles.copy().reset_index(drop=True)
        frame["atr"] = atr(frame, 14)
        closed = frame.iloc[:-1].copy()  # never use the forming candle
        if len(closed) < 30:
            return []

        highs, lows = self._pivots(closed)
        if len(highs) < 2 or len(lows) < 2:
            return []

        h1, h2 = highs[-2], highs[-1]
        l1, l2 = lows[-2], lows[-1]
        last = closed.iloc[-1]
        prev = closed.iloc[-2]
        a = float(last["atr"]) if pd.notna(last["atr"]) else 0.0
        if a <= 0:
            return []

        signals: list[StrategySignal] = []
        bullish = h2[1] > h1[1] and l2[1] > l1[1]
        bearish = h2[1] < h1[1] and l2[1] < l1[1]
        tolerance = a * self.pullback_tolerance_atr

        # Pullback into latest higher-low area + bullish rejection/continuation.
        if bullish:
            touched = float(last["low"]) <= l2[1] + tolerance
            confirmation = (
                float(last["close"]) > float(last["open"])
                and float(last["close"]) > float(prev["close"])
                and float(last["close"]) > l2[1]
            )
            if touched and confirmation:
                entry = float(last["close"])
                sl = l2[1] - a * self.stop_buffer_atr
                risk = entry - sl
                if risk > 0:
                    signals.append(
                        StrategySignal(
                            strategy_id=self.strategy_id,
                            direction="BUY",
                            timeframe="M5",
                            setup_time=str(last["time"]),
                            entry=entry,
                            stop_loss=sl,
                            take_profit=entry + self.reward_r * risk,
                            reason="HH_HL_PULLBACK_BULLISH_CONFIRMATION",
                            features={
                                "structure": "HH_HL",
                                "latest_swing_high": h2[1],
                                "latest_swing_low": l2[1],
                                "atr": a,
                                "reward_r": self.reward_r,
                            },
                        )
                    )

        # Pullback into latest lower-high area + bearish rejection/continuation.
        if bearish:
            touched = float(last["high"]) >= h2[1] - tolerance
            confirmation = (
                float(last["close"]) < float(last["open"])
                and float(last["close"]) < float(prev["close"])
                and float(last["close"]) < h2[1]
            )
            if touched and confirmation:
                entry = float(last["close"])
                sl = h2[1] + a * self.stop_buffer_atr
                risk = sl - entry
                if risk > 0:
                    signals.append(
                        StrategySignal(
                            strategy_id=self.strategy_id,
                            direction="SELL",
                            timeframe="M5",
                            setup_time=str(last["time"]),
                            entry=entry,
                            stop_loss=sl,
                            take_profit=entry - self.reward_r * risk,
                            reason="LL_LH_PULLBACK_BEARISH_CONFIRMATION",
                            features={
                                "structure": "LL_LH",
                                "latest_swing_high": h2[1],
                                "latest_swing_low": l2[1],
                                "atr": a,
                                "reward_r": self.reward_r,
                            },
                        )
                    )

        return signals
~~~

---

## 5. `strategies/support_resistance.py`

Original Git blob: `02ff15afc77eb3c38c79f89b81fbfc9ed92c3a8e`

~~~python
from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr


class SupportResistanceStrategy(StrategyModel):
    strategy_id = "SUPPORT_RESISTANCE"

    def __init__(
        self,
        lookback=80,
        pivot_span=2,
        cluster_atr=0.20,
        touch_atr=0.18,
        stop_atr=0.18,
        reward_r=1.5,
        min_stop_atr=1.5,
    ):
        self.lookback = lookback
        self.pivot_span = pivot_span
        self.cluster_atr = cluster_atr
        self.touch_atr = touch_atr
        self.stop_atr = stop_atr
        self.reward_r = reward_r
        self.min_stop_atr = min_stop_atr

    def _pivots(self, f):
        hs, ls = [], []
        s = self.pivot_span
        for i in range(s, len(f) - s):
            w = f.iloc[i - s:i + s + 1]
            if f.iloc[i].high >= w.high.max():
                hs.append(float(f.iloc[i].high))
            if f.iloc[i].low <= w.low.min():
                ls.append(float(f.iloc[i].low))
        return hs, ls

    def _level(self, values, tol):
        if len(values) < 2:
            return None
        best = None
        for v in values:
            group = [x for x in values if abs(x - v) <= tol]
            if len(group) >= 2 and (best is None or len(group) > len(best)):
                best = group
        return sum(best) / len(best) if best else None

    def scan(self, candles):
        if candles is None or len(candles) < 50:
            return []

        f = candles.iloc[:-1].tail(self.lookback).copy().reset_index(drop=True)
        f["atr"] = atr(f, 14)
        last = f.iloc[-1]
        a = float(last.atr) if pd.notna(last.atr) else 0.0
        if a <= 0:
            return []

        hs, ls = self._pivots(f)
        resistance = self._level(hs, a * self.cluster_atr)
        support = self._level(ls, a * self.cluster_atr)

        out = []
        o, c, h, l = map(float, (last.open, last.close, last.high, last.low))

        # Refined SL rule:
        # 1) invalidate beyond the actual level/rejection extreme;
        # 2) never use less than min_stop_atr of breathing room from entry.
        if support is not None and l <= support + a * self.touch_atr and c > support and c > o:
            structural_sl = min(l, support) - self.stop_atr * a
            volatility_floor = c - self.min_stop_atr * a
            sl = min(structural_sl, volatility_floor)
            risk = c - sl
            if risk > 0:
                out.append(
                    StrategySignal(
                        self.strategy_id,
                        "BUY",
                        "M5",
                        str(last.time),
                        c,
                        sl,
                        c + self.reward_r * risk,
                        "SUPPORT_REJECTION_REFINED_INVALIDATION",
                        {
                            "support": support,
                            "rejection_low": l,
                            "atr": a,
                            "min_stop_atr": self.min_stop_atr,
                            "reward_r": self.reward_r,
                        },
                    )
                )

        if resistance is not None and h >= resistance - a * self.touch_atr and c < resistance and c < o:
            structural_sl = max(h, resistance) + self.stop_atr * a
            volatility_floor = c + self.min_stop_atr * a
            sl = max(structural_sl, volatility_floor)
            risk = sl - c
            if risk > 0:
                out.append(
                    StrategySignal(
                        self.strategy_id,
                        "SELL",
                        "M5",
                        str(last.time),
                        c,
                        sl,
                        c - self.reward_r * risk,
                        "RESISTANCE_REJECTION_REFINED_INVALIDATION",
                        {
                            "resistance": resistance,
                            "rejection_high": h,
                            "atr": a,
                            "min_stop_atr": self.min_stop_atr,
                            "reward_r": self.reward_r,
                        },
                    )
                )

        return out
~~~

---

## 6. `strategies/momentum_scalp.py`

Original Git blob: `afcdb5e35e506ebcae99e8de2130b191363b47a6`

~~~python
from __future__ import annotations
import pandas as pd
from .base import StrategyModel, StrategySignal
from .indicators import atr


class MomentumScalpStrategy(StrategyModel):
    strategy_id = "MOMENTUM_SCALP"

    def __init__(
        self,
        body_atr=.9,
        body_ratio=.65,
        stop_atr=.2,
        reward_r=1.25,
        min_stop_atr=1.5,
    ):
        self.body_atr = body_atr
        self.body_ratio = body_ratio
        self.stop_atr = stop_atr
        self.reward_r = reward_r
        self.min_stop_atr = min_stop_atr

    def scan(self, candles):
        if candles is None or len(candles) < 25:
            return []

        f = candles.iloc[:-1].copy().reset_index(drop=True)
        f["atr"] = atr(f, 14)
        x = f.iloc[-1]

        a = float(x.atr) if pd.notna(x.atr) else 0.0
        rng = float(x.high - x.low)
        body = abs(float(x.close - x.open))
        if a <= 0 or rng <= 0 or body < a * self.body_atr or body / rng < self.body_ratio:
            return []

        c = float(x.close)
        out = []

        # Momentum already uses the displacement candle extreme as structural
        # invalidation. Refined v1 adds only a minimum ATR breathing-room floor.
        if c > float(x.open):
            structural_sl = float(x.low) - self.stop_atr * a
            volatility_floor = c - self.min_stop_atr * a
            sl = min(structural_sl, volatility_floor)
            r = c - sl
            if r > 0:
                out.append(
                    StrategySignal(
                        self.strategy_id,
                        "BUY",
                        "M5",
                        str(x.time),
                        c,
                        sl,
                        c + self.reward_r * r,
                        "BULLISH_MOMENTUM_REFINED_INVALIDATION",
                        {
                            "body_atr": body / a,
                            "body_ratio": body / rng,
                            "atr": a,
                            "min_stop_atr": self.min_stop_atr,
                        },
                    )
                )
        else:
            structural_sl = float(x.high) + self.stop_atr * a
            volatility_floor = c + self.min_stop_atr * a
            sl = max(structural_sl, volatility_floor)
            r = sl - c
            if r > 0:
                out.append(
                    StrategySignal(
                        self.strategy_id,
                        "SELL",
                        "M5",
                        str(x.time),
                        c,
                        sl,
                        c - self.reward_r * r,
                        "BEARISH_MOMENTUM_REFINED_INVALIDATION",
                        {
                            "body_atr": body / a,
                            "body_ratio": body / rng,
                            "atr": a,
                            "min_stop_atr": self.min_stop_atr,
                        },
                    )
                )

        return out
~~~

---

## 7. `server/signal_engine.py`

Original Git blob: `9d1e7da13ef5225c91c00bf4c89e69e4f2aa1ad3`

~~~python
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

from broker.mt5_client import MT5Client
from config import ACTIVE_MARKETS, DEMO_MAX_SIGNAL_AGE_MINUTES, DEMO_POLL_SECONDS, M5_BARS
from strategies import StrategyRegistry

from .personal_store import publish_signal, write_status
from .store import active_clients, enqueue_instruction, news_lock_enabled
from .reconnect import RetryState


def _setup_epoch(signal) -> float:
    value = str(signal.setup_time).replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _signal_key(market: str, signal) -> str:
    return f"{market}|{signal.strategy_id}|{signal.direction}|{signal.setup_time}"


def _legacy_signal_key(market, signal, offset_seconds):
    if not offset_seconds:
        return None
    broker_label = datetime.fromtimestamp(_setup_epoch(signal), timezone.utc) + timedelta(seconds=offset_seconds)
    return f"{market}|{signal.strategy_id}|{signal.direction}|{broker_label}"


def _wait_for_database(error, retries, stop):
    code = getattr(error, "sqlite_errorcode", 0)
    if (code & 0xFF) not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        raise error
    delay = retries.failed()
    write_status("signal_engine", state=retries.state, desired=True, retry_in=delay,
                 failures=retries.failures, message="Signal database busy; waiting to retry.")
    stop.wait(delay)


def main(stop=None) -> None:
    import threading
    stop = stop or threading.Event()
    write_status("signal_engine", state="CONNECTING", message="Connecting market data to MT5")
    print("Connecting signal engine market data to MT5...", flush=True)
    clients = {}
    retries = RetryState()
    database_retries = RetryState()
    for market, hint in ACTIVE_MARKETS.items():
        clients[market] = MT5Client(hint)

    registries = {
        market: StrategyRegistry(market=market)
        for market in clients
    }

    seen: set[str] = set()
    print("GOLD_AI OWNER SIGNAL ENGINE / AGORA ZION TRADER")
    print("Protected strategies run here; customer clients receive instructions only.")
    print("Ctrl+C to stop.")

    connected = False
    while not stop.is_set():
        if not connected:
            try:
                for client in clients.values():
                    client.connect()
                connected = True
            except Exception as exc:
                delay = retries.failed()
                write_status("signal_engine", state=retries.state, desired=True, retry_in=delay,
                             failures=retries.failures, message=f"Market data unavailable ({type(exc).__name__}); retrying.")
                mt5.shutdown()
                stop.wait(delay)
                continue
        try:
            locked = news_lock_enabled()
        except sqlite3.OperationalError as exc:
            _wait_for_database(exc, database_retries, stop)
            continue
        write_status("signal_engine", state="NEWS_LOCK" if locked else "SCANNING", markets=list(clients))
        if locked:
            database_retries.recovered()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] NEWS LOCK active — new entries blocked.")
            stop.wait(DEMO_POLL_SECONDS)
            continue

        now = datetime.now(timezone.utc).timestamp()
        database_busy = False
        for market, client in clients.items():
            if stop.is_set():
                break
            try:
                candles = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
            except Exception as exc:
                connected = False
                delay = retries.failed()
                write_status("signal_engine", state=retries.state, desired=True, retry_in=delay,
                             message=f"Market data interrupted ({type(exc).__name__}); reconnecting.")
                stop.wait(delay)
                break
            signals = registries[market].scan(candles)

            for signal in signals:
                if stop.is_set():
                    break
                key = _signal_key(market, signal)
                if key in seen:
                    continue

                age_seconds = now - _setup_epoch(signal)
                if age_seconds < -60 or age_seconds > DEMO_MAX_SIGNAL_AGE_MINUTES * 60:
                    seen.add(key)
                    continue

                legacy_key = _legacy_signal_key(market, signal, client.clock.offset_seconds)
                payload = {
                    "market": market,
                    "symbol_hint": market,
                    "strategy_id": signal.strategy_id,
                    "direction": signal.direction,
                    "setup_time": str(signal.setup_time),
                    "stop_loss": float(signal.stop_loss),
                    "take_profit": float(signal.take_profit),
                    "metadata": asdict(signal),
                    "time_basis": "UTC",
                    "broker_clock_offset_seconds": client.clock.offset_seconds,
                }
                encoded = json.dumps(payload, default=str, separators=(",", ":"))

                try:
                    publish_signal(key, payload, legacy_key=legacy_key)
                    queued = sum(enqueue_instruction(customer.id, key, encoded, legacy_key=legacy_key)
                                 for customer in active_clients())
                except sqlite3.OperationalError as exc:
                    # Unique keys make a partial dispatch safe to retry. Only
                    # mark a signal seen after each intended write can finish.
                    _wait_for_database(exc, database_retries, stop)
                    database_busy = True
                    break

                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"{market} {signal.strategy_id} {signal.direction} "
                    f"queued_for={queued}"
                )
                seen.add(key)

            if database_busy:
                break

        if database_busy:
            continue
        database_retries.recovered()
        if connected:
            if retries.recovered():
                write_status("signal_engine", state="RECOVERED", message="Market data recovered; scanning fresh setups.")
            stop.wait(DEMO_POLL_SECONDS)
    write_status("signal_engine", state="STOPPED", desired=False, message="Signal engine stopped.")


if __name__ == "__main__":
    try:
        main()
    finally:
        mt5.shutdown()
~~~

---

## 8. `broker/m15_trailing.py`

Original Git blob: `12b5f7ed7a30212621c87a81c08ebddcf91d108e`

~~~python
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

from strategies.indicators import atr


@dataclass(frozen=True)
class TrailResult:
    ticket: int
    changed: bool
    old_sl: float
    new_sl: float
    message: str


class M15StructureTrailingManager:
    """Structure-based trailing for M15_BREAKOUT positions only.

    Behaviour:
    - never loosens a stop;
    - does nothing until the trade has moved at least activation_r in favour;
    - then trails behind the most recent confirmed M5 swing (higher-low for BUY,
      lower-high for SELL) with a small ATR buffer;
    - subsequent confirmed swings ratchet the stop progressively.

    This implements the staged trail shown in the reviewed chart without
    hard-coding chart-specific prices.
    """

    def __init__(
        self,
        magic: int,
        activation_r: float = 1.0,
        swing_span: int = 2,
        atr_buffer: float = 0.15,
        lookback_bars: int = 120,
    ) -> None:
        self.magic = int(magic)
        self.activation_r = float(activation_r)
        self.swing_span = int(swing_span)
        self.atr_buffer = float(atr_buffer)
        self.lookback_bars = int(lookback_bars)

    @staticmethod
    def _is_m15_position(position: object) -> bool:
        comment = str(getattr(position, "comment", "") or "")
        return "M15_BREAKOUT" in comment

    def _candles(self, symbol: str) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, self.lookback_bars)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        f = pd.DataFrame(rates)
        f["time"] = pd.to_datetime(f["time"], unit="s", utc=True)
        # Ignore the forming M5 candle for trailing decisions.
        return f.iloc[:-1].copy().reset_index(drop=True)

    def _latest_confirmed_swing(self, f: pd.DataFrame, side: str) -> Optional[float]:
        s = self.swing_span
        if len(f) < 2 * s + 5:
            return None

        if side == "BUY":
            for i in range(len(f) - s - 1, s - 1, -1):
                w = f.iloc[i - s:i + s + 1]
                v = float(f.iloc[i]["low"])
                if v <= float(w["low"].min()):
                    return v
        else:
            for i in range(len(f) - s - 1, s - 1, -1):
                w = f.iloc[i - s:i + s + 1]
                v = float(f.iloc[i]["high"])
                if v >= float(w["high"].max()):
                    return v
        return None

    @staticmethod
    def _position_side(position: object) -> str:
        return "BUY" if int(position.type) == int(mt5.POSITION_TYPE_BUY) else "SELL"

    def _activation_reached(self, p: object) -> bool:
        entry = float(p.price_open)
        current = float(p.price_current)
        sl = float(p.sl)
        if sl <= 0:
            return False

        # Before the first trail, current SL is the original strategy stop.
        # After trailing has begun, activation remains true for any position
        # already protected at or beyond entry.
        side = self._position_side(p)
        if side == "BUY" and sl >= entry:
            return True
        if side == "SELL" and sl <= entry:
            return True

        initial_r = abs(entry - sl)
        if initial_r <= 0:
            return False

        favourable = (current - entry) if side == "BUY" else (entry - current)
        return favourable >= self.activation_r * initial_r

    def _candidate_sl(self, p: object, f: pd.DataFrame) -> Optional[float]:
        if f.empty:
            return None

        f["atr"] = atr(f, 14)
        last_atr = float(f.iloc[-1]["atr"]) if pd.notna(f.iloc[-1]["atr"]) else 0.0
        if last_atr <= 0:
            return None

        side = self._position_side(p)
        swing = self._latest_confirmed_swing(f, side)
        if swing is None:
            return None

        if side == "BUY":
            return float(swing - self.atr_buffer * last_atr)
        return float(swing + self.atr_buffer * last_atr)

    @staticmethod
    def _improves_stop(p: object, candidate: float) -> bool:
        old_sl = float(p.sl)
        current = float(p.price_current)
        side = "BUY" if int(p.type) == int(mt5.POSITION_TYPE_BUY) else "SELL"

        if side == "BUY":
            return candidate > old_sl and candidate < current
        return candidate < old_sl and candidate > current

    def _modify_sl(self, p: object, new_sl: float) -> TrailResult:
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(p.ticket),
            "symbol": str(p.symbol),
            "sl": float(new_sl),
            "tp": float(p.tp),
        }
        result = mt5.order_send(request)
        if result is None:
            code, message = mt5.last_error()
            return TrailResult(int(p.ticket), False, float(p.sl), float(p.sl),
                               f"TRAIL_FAILED {code}: {message}")

        done = int(result.retcode) == int(getattr(mt5, "TRADE_RETCODE_DONE", 10009))
        return TrailResult(
            int(p.ticket),
            done,
            float(p.sl),
            float(new_sl) if done else float(p.sl),
            str(getattr(result, "comment", "")),
        )

    @staticmethod
    def _pip_size(symbol: str) -> float:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Symbol info unavailable for {symbol}.")
        point = float(info.point)
        digits = int(info.digits)
        name = str(symbol).upper()

        # GOLD convention used by this project:
        # 1 pip = 10 MT5 points. Example on a 2-digit XAUUSD quote:
        # point=0.01 -> pip=0.10, therefore 12 pips = 1.20 in price.
        if "XAU" in name or "GOLD" in name:
            return point * 10.0

        # Standard FX convention: 5/3-digit quotes use 10 points per pip.
        return point * 10.0 if digits in (3, 5) else point

    def protect_older_positions(
        self,
        symbol: str,
        direction: str,
        profit_lock_pips: float,
    ) -> list[TrailResult]:
        """Lock older same-direction GOLD_AI positions into a small profit.

        Called immediately after a fresh position is opened. The newest
        position keeps its strategy SL; every older same-side position is
        considered for an SL at entry +/- profit_lock_pips. Stops only move
        forward, never backward, and are changed only when broker distance
        rules and current price make the protected stop valid.
        """
        positions = [
            p for p in (mt5.positions_get(symbol=symbol) or ())
            if int(getattr(p, "magic", -1)) == self.magic
            and self._position_side(p) == direction
        ]
        if len(positions) < 2:
            return []

        positions.sort(
            key=lambda p: (
                int(getattr(p, "time_msc", 0) or 0),
                int(getattr(p, "time", 0) or 0),
                int(getattr(p, "ticket", 0) or 0),
            )
        )
        newest = positions[-1]
        pip = self._pip_size(symbol)
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            return []

        min_stop_distance = float(getattr(info, "trade_stops_level", 0) or 0) * float(info.point)
        results: list[TrailResult] = []

        for p in positions[:-1]:
            entry = float(p.price_open)
            old_sl = float(p.sl)
            if direction == "BUY":
                target = entry + float(profit_lock_pips) * pip
                market_exit = float(tick.bid)
                if market_exit <= target + min_stop_distance:
                    continue
                if old_sl > 0 and target <= old_sl:
                    continue
            else:
                target = entry - float(profit_lock_pips) * pip
                market_exit = float(tick.ask)
                if market_exit >= target - min_stop_distance:
                    continue
                if old_sl > 0 and target >= old_sl:
                    continue

            results.append(self._modify_sl(p, target))

        return results

    def update_all(self) -> list[TrailResult]:
        positions = mt5.positions_get() or ()
        results: list[TrailResult] = []

        for p in positions:
            if int(getattr(p, "magic", -1)) != self.magic:
                continue
            if not self._is_m15_position(p):
                continue
            if not self._activation_reached(p):
                continue

            f = self._candles(str(p.symbol))
            candidate = self._candidate_sl(p, f)
            if candidate is None or not self._improves_stop(p, candidate):
                continue

            results.append(self._modify_sl(p, candidate))

        return results
~~~

---

## 9. `backtesting/engine.py`

Original Git blob: `3b2d70b4c67f58a736e55ca73773404883970acf`

~~~python
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import math
import pandas as pd
from strategies import StrategyRegistry

class BacktestEngine:
    def __init__(self,reports_dir:Path,warmup_bars=100,max_hold_bars=60,history_window=250,starting_balance=10000.0,risk_pct=0.9):
        self.reports_dir=reports_dir; self.warmup_bars=warmup_bars; self.max_hold_bars=max_hold_bars
        self.history_window=history_window; self.starting_balance=float(starting_balance); self.risk_pct=float(risk_pct)
        self.reports_dir.mkdir(parents=True,exist_ok=True)

    def _resolve(self,s,future):
        entry=float(s.entry); sl=float(s.stop_loss); tp=float(s.take_profit); risk=abs(entry-sl)
        if risk<=0:return None
        mfe=mae=0.0
        for held,(_,b) in enumerate(future.iterrows(),1):
            hi=float(b.high); lo=float(b.low)
            if s.direction=="BUY": mfe=max(mfe,(hi-entry)/risk); mae=max(mae,(entry-lo)/risk); hit_sl=lo<=sl; hit_tp=hi>=tp
            else: mfe=max(mfe,(entry-lo)/risk); mae=max(mae,(hi-entry)/risk); hit_sl=hi>=sl; hit_tp=lo<=tp
            if hit_sl and hit_tp:return "SL",-1.0,held,mfe,mae,"BOTH_TOUCHED_SL_FIRST"
            if hit_sl:return "SL",-1.0,held,mfe,mae,"SL"
            if hit_tp:return "TP",abs(tp-entry)/risk,held,mfe,mae,"TP"
            if held>=self.max_hold_bars:break
        if future.empty:return None
        b=future.iloc[min(len(future),self.max_hold_bars)-1]; px=float(b.close)
        r=(px-entry)/risk if s.direction=="BUY" else (entry-px)/risk
        return "TIME",r,min(len(future),self.max_hold_bars),mfe,mae,"MAX_HOLD"

    def run(self,candles:pd.DataFrame):
        registry=StrategyRegistry(); rows=[]; seen=set()
        for i in range(self.warmup_bars,len(candles)-2):
            start=max(0,i-self.history_window)
            history=candles.iloc[start:i+1].copy()
            for s in registry.scan(history):
                key=(s.strategy_id,s.direction,s.setup_time)
                if key in seen:continue
                seen.add(key); outcome=self._resolve(s,candles.iloc[i:i+1+self.max_hold_bars])
                if outcome is None:continue
                exit_type,r_mult,bars_held,mfe,mae,exit_reason=outcome
                row=asdict(s); row["features"]=repr(row["features"])
                row.update({"exit_type":exit_type,"r_multiple":r_mult,"bars_held":bars_held,"mfe_r":mfe,"mae_r":mae,"exit_reason":exit_reason})
                rows.append(row)
        trades=pd.DataFrame(rows)
        if not trades.empty: trades=trades.sort_values(["setup_time","strategy_id"]).reset_index(drop=True)
        trades.to_csv(self.reports_dir/"backtest_trades.csv",index=False)
        summary=self._summary(trades); summary.to_csv(self.reports_dir/"backtest_summary.csv",index=False)
        equity=self._equity_reports(trades); equity.to_csv(self.reports_dir/"backtest_equity.csv",index=False)
        return trades,summary,equity

    def _stats(self,rs):
        rs=pd.Series(rs,dtype=float); wins=int((rs>0).sum()); losses=int((rs<0).sum())
        gw=float(rs[rs>0].sum()); gl=abs(float(rs[rs<0].sum())); eq=rs.cumsum(); dd=eq-eq.cummax()
        return wins,losses,gw/gl if gl else math.inf,abs(float(dd.min())) if len(dd) else 0.0

    def _balance_path(self,g):
        bal=self.starting_balance; maximum=minimum=bal; path=[]
        for _,r in g.iterrows():
            risk_cash=bal*(self.risk_pct/100.0); pnl=risk_cash*float(r.r_multiple); bal+=pnl
            maximum=max(maximum,bal); minimum=min(minimum,bal); path.append((bal,pnl,risk_cash))
        return bal,maximum,minimum,path

    def _summary(self,trades):
        cols=["strategy_id","trades","wins","losses","win_rate_pct","net_r","avg_r","profit_factor","max_drawdown_r","starting_balance","max_balance","min_balance","ending_balance","return_pct"]
        if trades.empty:return pd.DataFrame(columns=cols)
        rows=[]
        for sid,g in trades.groupby("strategy_id",sort=False):
            g=g.sort_values("setup_time"); rs=g.r_multiple.astype(float); wins,losses,pf,mdd=self._stats(rs); end,mx,mn,_=self._balance_path(g)
            rows.append({"strategy_id":sid,"trades":len(g),"wins":wins,"losses":losses,"win_rate_pct":100*wins/len(g),"net_r":float(rs.sum()),"avg_r":float(rs.mean()),"profit_factor":pf,"max_drawdown_r":mdd,"starting_balance":self.starting_balance,"max_balance":mx,"min_balance":mn,"ending_balance":end,"return_pct":100*(end/self.starting_balance-1)})
        return pd.DataFrame(rows).sort_values("net_r",ascending=False)

    def _equity_reports(self,trades):
        if trades.empty:return pd.DataFrame(columns=["portfolio","setup_time","strategy_id","r_multiple","risk_cash","pnl","balance"])
        out=[]; groups=[("ALL_STRATEGIES",trades.sort_values(["setup_time","strategy_id"]))]+[(sid,g.sort_values("setup_time")) for sid,g in trades.groupby("strategy_id")]
        for name,g in groups:
            _,_,_,path=self._balance_path(g)
            for (_,r),(bal,pnl,risk_cash) in zip(g.iterrows(),path):
                out.append({"portfolio":name,"setup_time":r.setup_time,"strategy_id":r.strategy_id,"r_multiple":r.r_multiple,"risk_cash":risk_cash,"pnl":pnl,"balance":bal})
        return pd.DataFrame(out)

    def combined_summary(self,trades):
        if trades.empty:return {}
        g=trades.sort_values(["setup_time","strategy_id"]); rs=g.r_multiple.astype(float); wins,losses,pf,mdd=self._stats(rs); end,mx,mn,_=self._balance_path(g)
        return {"strategy_id":"ALL_STRATEGIES","trades":len(g),"wins":wins,"losses":losses,"win_rate_pct":100*wins/len(g),"net_r":float(rs.sum()),"avg_r":float(rs.mean()),"profit_factor":pf,"max_drawdown_r":mdd,"starting_balance":self.starting_balance,"max_balance":mx,"min_balance":mn,"ending_balance":end,"return_pct":100*(end/self.starting_balance-1)}
~~~

---

## 10. `config.py`

Original Git blob: `d901023c28cfa1efa094bd3fd002172c9984f8bd`

~~~python
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
~~~

---

