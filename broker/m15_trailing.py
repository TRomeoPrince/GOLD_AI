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
