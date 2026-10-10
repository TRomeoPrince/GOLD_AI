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
