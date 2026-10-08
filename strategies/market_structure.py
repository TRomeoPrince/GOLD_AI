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
