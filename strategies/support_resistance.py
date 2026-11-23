from __future__ import annotations

import pandas as pd

from .base import StrategyModel, StrategySignal
from .indicators import atr


class SupportResistanceStrategy(StrategyModel):
    """Closed-bar horizontal S/R: independent touches and actual rejection.

    min_touches counts the current reaction (not only old pivot candles).
    2 = first rejection + reconfirmation; 3 = two prior tests + reaction.
    These are testable engineering settings, not empirically proven filters.
    """
    strategy_id = "SUPPORT_RESISTANCE"

    def __init__(
        self, lookback=80, pivot_span=2, cluster_atr=0.20,
        touch_atr=0.18, stop_atr=0.18, reward_r=1.5, min_stop_atr=1.5,
        min_touches=2, min_touch_spacing=6, wick_min_ratio=0.40,
        reaction_wick_min_ratio=0.20, penetration_atr=0.30,
        max_level_age=None,
    ):
        if min_touches < 2 or min_touch_spacing < 1:
            raise ValueError("Require two or more independent touches.")
        self.lookback, self.pivot_span = lookback, pivot_span
        self.cluster_atr, self.touch_atr = cluster_atr, touch_atr
        self.stop_atr, self.reward_r, self.min_stop_atr = stop_atr, reward_r, min_stop_atr
        self.min_touches, self.min_touch_spacing = min_touches, min_touch_spacing
        self.wick_min_ratio, self.reaction_wick_min_ratio = wick_min_ratio, reaction_wick_min_ratio
        self.penetration_atr = penetration_atr
        self.max_level_age = lookback if max_level_age is None else max_level_age

    def _pivots(self, f):
        hs, ls = [], []
        span = self.pivot_span
        # Both confirmation bars are closed. Current reaction never becomes
        # a historical pivot and cannot be counted twice.
        for i in range(span, len(f) - span):
            window = f.iloc[i - span:i + span + 1]
            if f.iloc[i].high >= window.high.max():
                hs.append((i, float(f.iloc[i].high)))
            if f.iloc[i].low <= window.low.min():
                ls.append((i, float(f.iloc[i].low)))
        return hs, ls

    def _clusters(self, pivots, tolerance, reaction_index):
        levels, seen = [], set()
        for _, seed in pivots:
            close_pivots = [(i, value) for i, value in pivots if abs(value - seed) <= tolerance]
            separate = []
            for index, value in close_pivots:
                if (not separate or index - separate[-1][0] >= self.min_touch_spacing):
                    separate.append((index, value))
            if len(separate) < self.min_touches - 1:
                continue
            if reaction_index - separate[-1][0] < self.min_touch_spacing:
                continue
            if reaction_index - separate[0][0] > self.max_level_age:
                continue
            signature = tuple(index for index, _ in separate)
            if signature in seen:
                continue
            seen.add(signature)
            levels.append((sum(v for _, v in separate) / len(separate), len(separate)))
        return levels

    @staticmethod
    def _engulfs(current, previous, side):
        o, c = float(current.open), float(current.close)
        po, pc = float(previous.open), float(previous.close)
        if side == "BUY":
            return pc < po and c > o and o <= pc and c >= po
        return pc > po and c < o and o >= pc and c <= po

    @staticmethod
    def _wick_ratio(candle, side):
        o, c, h, l = map(float, (candle.open, candle.close, candle.high, candle.low))
        if h <= l:
            return 0.0
        wick = min(o, c) - l if side == "BUY" else h - max(o, c)
        return max(wick, 0.0) / (h - l)

    def _reaction(self, f, level, a, side):
        current, previous = f.iloc[-1], f.iloc[-2]
        touch = self.touch_atr * a
        penetration = self.penetration_atr * a

        def at_level(bar):
            low, high = float(bar.low), float(bar.high)
            if side == "BUY":
                return level - penetration <= low <= level + touch
            return level - touch <= high <= level + penetration

        c, o = float(current.close), float(current.open)
        last_close = float(previous.close)
        # Approach from the correct side; avoid deep breaks of the level.
        if side == "BUY":
            approach = last_close >= level - penetration
            direct = c > o and c > level and at_level(current) and self._wick_ratio(current, side) >= self.wick_min_ratio
            follow = (c > level and at_level(previous)
                      and float(previous.close) >= level - touch
                      and self._wick_ratio(previous, side) >= self.reaction_wick_min_ratio
                      and self._engulfs(current, previous, side))
        else:
            approach = last_close <= level + penetration
            direct = c < o and c < level and at_level(current) and self._wick_ratio(current, side) >= self.wick_min_ratio
            follow = (c < level and at_level(previous)
                      and float(previous.close) <= level + touch
                      and self._wick_ratio(previous, side) >= self.reaction_wick_min_ratio
                      and self._engulfs(current, previous, side))
        if not approach or not (direct or follow):
            return None
        # If engulfing confirms a prior reaction, use that reaction's extreme.
        extreme = min(float(previous.low), float(current.low)) if follow and side == "BUY" else (
            max(float(previous.high), float(current.high)) if follow else
            (float(current.low) if side == "BUY" else float(current.high))
        )
        return "ENGULFING_AFTER_REACTION" if follow else "REJECTION_WICK", extreme

    def scan(self, candles):
        if candles is None or len(candles) < 50:
            return []

        f = candles.iloc[:-1].tail(self.lookback).copy().reset_index(drop=True)
        f["atr"] = atr(f, 14)
        last = f.iloc[-1]
        a = float(last.atr) if pd.notna(last.atr) else 0.0
        if a <= 0:
            return []
        highs, lows = self._pivots(f)
        entry = float(last.close)
        out = []
        for side, pivots, field in (("BUY", lows, "support"), ("SELL", highs, "resistance")):
            candidates = []
            for level, previous_touches in self._clusters(pivots, a * self.cluster_atr, len(f) - 2):
                result = self._reaction(f, level, a, side)
                if result is not None:
                    pattern, extreme = result
                    candidates.append((level, previous_touches, pattern, extreme))
            if not candidates:
                continue
            # Consider ALL clusters inside the current rejection zone; select
            # the strongest, with distance as a tie-breaker.
            level, prior, pattern, extreme = min(
                candidates, key=lambda item: (-item[1], abs(entry - item[0]))
            )
            if side == "BUY":
                sl = min(min(extreme, level) - self.stop_atr * a,
                         entry - self.min_stop_atr * a)
                risk = entry - sl
                tp = entry + self.reward_r * risk
            else:
                sl = max(max(extreme, level) + self.stop_atr * a,
                         entry + self.min_stop_atr * a)
                risk = sl - entry
                tp = entry - self.reward_r * risk
            if risk <= 0:
                continue
            out.append(StrategySignal(
                self.strategy_id, side, "M5", str(last.time),
                entry, sl, tp, f"{field.upper()}_{pattern}",
                {field: level, "reaction_extreme": extreme, "atr": a,
                 "prior_independent_touches": prior,
                 "total_touches": prior + 1, "min_touch_spacing": self.min_touch_spacing,
                 "confirmation": pattern, "min_stop_atr": self.min_stop_atr,
                 "reward_r": self.reward_r},
            ))
        return out
