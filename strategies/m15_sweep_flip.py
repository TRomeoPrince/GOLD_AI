from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Optional

import pandas as pd

from .base import StrategyModel, StrategySignal


@dataclass(frozen=True)
class SessionWindow:
    start_hour: int
    end_hour: int

    def contains(self, ts: pd.Timestamp) -> bool:
        h = int(ts.hour)
        if self.start_hour < self.end_hour:
            return self.start_hour <= h < self.end_hour
        return h >= self.start_hour or h < self.end_hour


class M15SweepFlipStrategy(StrategyModel):
    """Video-derived M15 Sweep & Flip Protocol.

    Confirmed strategy concepts:
    - H1 directional bias;
    - most recent Asian-session high/low are liquidity pools;
    - during the Asian -> London transition, London sweeps one side;
    - M15 must flip/reclaim back inside the swept Asian boundary;
    - buy after an Asian-low sweep/reclaim when H1 bias is bullish;
    - sell after an Asian-high sweep/reclaim when H1 bias is bearish;
    - SL beyond the sweep extreme;
    - target opposite Asian liquidity only if that target offers at least 2R.

    IMPORTANT: exact session clock boundaries were not recoverable from the
    source handoff. They are therefore REQUIRED inputs rather than silently
    invented defaults.
    """

    strategy_id = "M15_SWEEP_FLIP"

    def __init__(
        self,
        asian_start_hour: Optional[int] = None,
        asian_end_hour: Optional[int] = None,
        london_start_hour: Optional[int] = None,
        london_end_hour: Optional[int] = None,
        h1_pivot_span: int = 2,
        stop_buffer_fraction: float = 0.0,
        minimum_reward_r: float = 2.0,
    ) -> None:
        hours = [asian_start_hour, asian_end_hour, london_start_hour, london_end_hour]
        if any(v is None for v in hours):
            raise ValueError(
                "M15 Sweep & Flip requires explicit broker-time session hours: "
                "asian_start_hour, asian_end_hour, london_start_hour, london_end_hour."
            )
        for v in hours:
            if not 0 <= int(v) <= 23:
                raise ValueError("Session hours must be integers from 0 to 23.")

        self.asian = SessionWindow(int(asian_start_hour), int(asian_end_hour))
        self.london = SessionWindow(int(london_start_hour), int(london_end_hour))
        self.h1_pivot_span = int(h1_pivot_span)
        self.stop_buffer_fraction = float(stop_buffer_fraction)
        self.minimum_reward_r = float(minimum_reward_r)

    @staticmethod
    def _completed_m15(candles: pd.DataFrame) -> pd.DataFrame:
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
        return bars[bars["count"] == 3].drop(columns="count").dropna().reset_index()

    @staticmethod
    def _completed_h1(candles: pd.DataFrame) -> pd.DataFrame:
        closed = candles.iloc[:-1].copy()
        if closed.empty:
            return pd.DataFrame()
        f = closed.set_index("time").sort_index()
        bars = f.resample("1h", label="right", closed="left").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            count=("close", "count"),
        )
        return bars[bars["count"] == 12].drop(columns="count").dropna().reset_index()

    def _pivots(self, frame: pd.DataFrame):
        highs, lows = [], []
        s = self.h1_pivot_span
        for i in range(s, len(frame) - s):
            w = frame.iloc[i - s:i + s + 1]
            h = float(frame.iloc[i]["high"])
            l = float(frame.iloc[i]["low"])
            if h >= float(w["high"].max()):
                highs.append(h)
            if l <= float(w["low"].min()):
                lows.append(l)
        return highs, lows

    def _h1_bias(self, h1: pd.DataFrame) -> Optional[str]:
        highs, lows = self._pivots(h1)
        if len(highs) < 2 or len(lows) < 2:
            return None
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            return "BULLISH"
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            return "BEARISH"
        return None

    def _asian_range_before(self, m15: pd.DataFrame, ts: pd.Timestamp):
        day = ts.normalize()
        prior = m15[m15["time"] < ts].copy()
        if prior.empty:
            return None

        # Choose the most recent completed Asian session. Works across midnight.
        candidates = []
        for offset in (0, -1):
            d = day + pd.Timedelta(days=offset)
            mask = prior["time"].apply(
                lambda x: self.asian.contains(x) and (
                    x.normalize() == d
                    or self.asian.start_hour > self.asian.end_hour
                    and (x.normalize() == d or x.normalize() == d + pd.Timedelta(days=1))
                )
            )
            session = prior[mask]
            if len(session):
                candidates.append(session)

        if not candidates:
            return None
        session = candidates[-1]
        return float(session["high"].max()), float(session["low"].min())

    def scan(self, candles) -> list[StrategySignal]:
        if candles is None or len(candles) < 300:
            return []

        m15 = self._completed_m15(candles)
        h1 = self._completed_h1(candles)
        if len(m15) < 20 or len(h1) < 10:
            return []

        flip = m15.iloc[-1]
        ts = pd.Timestamp(flip["time"])
        if not self.london.contains(ts):
            return []

        bias = self._h1_bias(h1)
        if bias is None:
            return []

        asian = self._asian_range_before(m15, ts)
        if asian is None:
            return []
        asian_high, asian_low = asian

        o = float(flip["open"])
        h = float(flip["high"])
        l = float(flip["low"])
        c = float(flip["close"])

        out: list[StrategySignal] = []

        # Bullish Sweep & Flip: Asian low is swept, M15 closes/reclaims back
        # inside the range, aligned with bullish H1 structure.
        if bias == "BULLISH" and l < asian_low and c > asian_low and c > o:
            entry = c
            sweep_depth = asian_low - l
            sl = l - self.stop_buffer_fraction * sweep_depth
            risk = entry - sl
            opposite_liquidity = asian_high
            reward = opposite_liquidity - entry
            if risk > 0 and reward / risk >= self.minimum_reward_r:
                out.append(
                    StrategySignal(
                        self.strategy_id,
                        "BUY",
                        "M15",
                        str(ts),
                        entry,
                        sl,
                        opposite_liquidity,
                        "ASIAN_LOW_SWEEP_M15_RECLAIM_H1_BULLISH",
                        {
                            "h1_bias": bias,
                            "asian_high": asian_high,
                            "asian_low": asian_low,
                            "sweep_low": l,
                            "minimum_reward_r": self.minimum_reward_r,
                            "actual_reward_r": reward / risk,
                        },
                    )
                )

        # Bearish mirror.
        if bias == "BEARISH" and h > asian_high and c < asian_high and c < o:
            entry = c
            sweep_depth = h - asian_high
            sl = h + self.stop_buffer_fraction * sweep_depth
            risk = sl - entry
            opposite_liquidity = asian_low
            reward = entry - opposite_liquidity
            if risk > 0 and reward / risk >= self.minimum_reward_r:
                out.append(
                    StrategySignal(
                        self.strategy_id,
                        "SELL",
                        "M15",
                        str(ts),
                        entry,
                        sl,
                        opposite_liquidity,
                        "ASIAN_HIGH_SWEEP_M15_RECLAIM_H1_BEARISH",
                        {
                            "h1_bias": bias,
                            "asian_high": asian_high,
                            "asian_low": asian_low,
                            "sweep_high": h,
                            "minimum_reward_r": self.minimum_reward_r,
                            "actual_reward_r": reward / risk,
                        },
                    )
                )

        return out
