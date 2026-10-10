from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


def _load_mt5_export(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep="\t")
    frame.columns = [c.strip("<>") for c in frame.columns]
    frame["time"] = pd.to_datetime(
        frame["DATE"] + " " + frame["TIME"],
        format="%Y.%m.%d %H:%M:%S",
    )
    return (
        frame.rename(
            columns={"OPEN":"open","HIGH":"high","LOW":"low","CLOSE":"close","SPREAD":"spread"}
        )[["time","open","high","low","close","spread"]]
        .sort_values("time")
        .reset_index(drop=True)
    )


def _resample_complete(frame: pd.DataFrame, rule: str, expected: int) -> pd.DataFrame:
    bars = frame.set_index("time").resample(rule, label="right", closed="left").agg(
        open=("open","first"),
        high=("high","max"),
        low=("low","min"),
        close=("close","last"),
        count=("close","count"),
    )
    return bars[bars["count"] == expected].drop(columns="count").dropna().reset_index()


def _atr(frame: pd.DataFrame, period: int = 14) -> np.ndarray:
    h = frame.high.to_numpy(float)
    l = frame.low.to_numpy(float)
    c = frame.close.to_numpy(float)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h-l, np.abs(h-pc), np.abs(l-pc)]), axis=0)
    return pd.Series(tr).rolling(period).mean().to_numpy()


class SweepFlipBacktester:
    """Strict no-lookahead backtester for the current M15 Sweep & Flip system.

    Session clock boundaries are explicit constructor arguments because the
    video-derived handoff did not preserve exact clock times/timezone.
    """

    def __init__(
        self,
        asian_start_hour: int,
        asian_end_hour: int,
        london_start_hour: int,
        london_end_hour: int,
        minimum_reward_r: float = 2.0,
        starting_balance: float = 10000.0,
        risk_pct: float = 0.9,
        trailing_enabled: bool = True,
        trail_activate_r: float = 1.0,
        trail_span: int = 2,
        trail_atr_buffer: float = 0.15,
    ) -> None:
        self.asian_start = int(asian_start_hour)
        self.asian_end = int(asian_end_hour)
        self.london_start = int(london_start_hour)
        self.london_end = int(london_end_hour)
        self.minimum_reward_r = float(minimum_reward_r)
        self.starting_balance = float(starting_balance)
        self.risk_pct = float(risk_pct)
        self.trailing_enabled = bool(trailing_enabled)
        self.trail_activate_r = float(trail_activate_r)
        self.trail_span = int(trail_span)
        self.trail_atr_buffer = float(trail_atr_buffer)

        if self.asian_start >= self.asian_end or self.london_start >= self.london_end:
            raise ValueError(
                "This research backtester currently requires same-day hour windows "
                "(start < end)."
            )

    @staticmethod
    def _h1_bias_series(h1: pd.DataFrame, span: int = 2) -> np.ndarray:
        h = h1.high.to_numpy(float)
        l = h1.low.to_numpy(float)
        n = len(h1)
        ph = np.zeros(n, dtype=bool)
        pl = np.zeros(n, dtype=bool)
        for i in range(span, n-span):
            ph[i] = h[i] >= h[i-span:i+span+1].max()
            pl[i] = l[i] <= l[i-span:i+span+1].min()

        bias = np.empty(n, dtype=object)
        bias[:] = None
        highs, lows = [], []
        for t in range(n):
            confirmed = t - span
            if confirmed >= span:
                if ph[confirmed]:
                    highs.append(h[confirmed])
                if pl[confirmed]:
                    lows.append(l[confirmed])
            if len(highs) >= 2 and len(lows) >= 2:
                if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
                    bias[t] = "BULLISH"
                elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
                    bias[t] = "BEARISH"
        return bias

    @staticmethod
    def _confirmed_swings(m5: pd.DataFrame, span: int):
        h = m5.high.to_numpy(float)
        l = m5.low.to_numpy(float)
        n = len(m5)
        ph = np.zeros(n, dtype=bool)
        pl = np.zeros(n, dtype=bool)

        for i in range(span, n-span):
            ph[i] = h[i] >= h[i-span:i+span+1].max()
            pl[i] = l[i] <= l[i-span:i+span+1].min()

        latest_h = np.full(n, np.nan)
        latest_l = np.full(n, np.nan)
        sh = sl = np.nan
        for t in range(n):
            confirmed = t - span
            if confirmed >= span:
                if ph[confirmed]:
                    sh = h[confirmed]
                if pl[confirmed]:
                    sl = l[confirmed]
            latest_h[t] = sh
            latest_l[t] = sl
        return latest_l, latest_h

    def run_csv(self, path: Path, market: str):
        return self.run(_load_mt5_export(path), market)

    def run(self, frame: pd.DataFrame, market: str):
        m5 = frame.copy().reset_index(drop=True)
        m5["atr"] = _atr(m5)
        m15 = _resample_complete(m5, "15min", 3)
        h1 = _resample_complete(m5, "1h", 12)

        h1_bias = self._h1_bias_series(h1)
        h1_times = h1.time.to_numpy("datetime64[ns]")
        m5_times = m5.time.to_numpy("datetime64[ns]")
        latest_low, latest_high = self._confirmed_swings(m5, self.trail_span)

        mh = m5.high.to_numpy(float)
        ml = m5.low.to_numpy(float)
        mc = m5.close.to_numpy(float)
        mo = m5.open.to_numpy(float)
        ma = m5.atr.to_numpy(float)

        m15["date"] = m15.time.dt.normalize()
        asian_ranges = {}
        mask = (
            (m15.time.dt.hour >= self.asian_start)
            & (m15.time.dt.hour < self.asian_end)
        )
        for date, group in m15[mask].groupby("date"):
            asian_ranges[date] = (float(group.high.max()), float(group.low.min()))

        rows = []
        for setup in m15.itertuples(index=False):
            ts = setup.time
            if not self.london_start <= ts.hour < self.london_end:
                continue
            asian = asian_ranges.get(ts.normalize())
            if asian is None:
                continue

            hi_idx = np.searchsorted(h1_times, np.datetime64(ts), side="right") - 1
            if hi_idx < 0:
                continue
            bias = h1_bias[hi_idx]
            if bias is None:
                continue

            asian_high, asian_low = asian
            direction = None
            if (
                bias == "BULLISH"
                and setup.low < asian_low
                and setup.close > asian_low
                and setup.close > setup.open
            ):
                direction = "BUY"
                initial_sl = float(setup.low)
                tp = asian_high
            elif (
                bias == "BEARISH"
                and setup.high > asian_high
                and setup.close < asian_high
                and setup.close < setup.open
            ):
                direction = "SELL"
                initial_sl = float(setup.high)
                tp = asian_low
            else:
                continue

            # Strict no-lookahead: confirmation is known only at M15 close,
            # therefore execution starts at the next M5 bar open.
            entry_idx = np.searchsorted(m5_times, np.datetime64(ts), side="left")
            if entry_idx >= len(m5):
                continue
            entry = mo[entry_idx]

            risk = entry - initial_sl if direction == "BUY" else initial_sl - entry
            reward = tp - entry if direction == "BUY" else entry - tp
            if risk <= 0 or reward <= 0 or reward / risk < self.minimum_reward_r:
                continue

            active_sl = initial_sl
            mfe = mae = 0.0
            trail_updates = 0
            exit_row = None

            for k in range(entry_idx, len(m5)):
                high, low, close = mh[k], ml[k], mc[k]
                if direction == "BUY":
                    mfe = max(mfe, (high-entry)/risk)
                    mae = max(mae, (entry-low)/risk)
                    hit_sl = low <= active_sl
                    hit_tp = high >= tp
                else:
                    mfe = max(mfe, (entry-low)/risk)
                    mae = max(mae, (high-entry)/risk)
                    hit_sl = high >= active_sl
                    hit_tp = low <= tp

                # Conservative same-bar ordering.
                if hit_sl:
                    r = (
                        (active_sl-entry)/risk
                        if direction == "BUY"
                        else (entry-active_sl)/risk
                    )
                    exit_row = (k, active_sl, "TRAIL_SL" if active_sl != initial_sl else "SL", r)
                    break
                if hit_tp:
                    exit_row = (k, tp, "TP", reward/risk)
                    break

                # Trail update is based only on bars confirmed through k and
                # becomes effective on the following bar.
                if self.trailing_enabled and mfe >= self.trail_activate_r and not np.isnan(ma[k]):
                    swing = latest_low[k] if direction == "BUY" else latest_high[k]
                    if not np.isnan(swing):
                        candidate = (
                            swing - self.trail_atr_buffer * ma[k]
                            if direction == "BUY"
                            else swing + self.trail_atr_buffer * ma[k]
                        )
                        if direction == "BUY" and candidate > active_sl and candidate < close:
                            active_sl = candidate
                            trail_updates += 1
                        elif direction == "SELL" and candidate < active_sl and candidate > close:
                            active_sl = candidate
                            trail_updates += 1

            if exit_row is None:
                k = len(m5)-1
                px = mc[-1]
                r = (px-entry)/risk if direction == "BUY" else (entry-px)/risk
                exit_row = (k, px, "EODATA", r)

            k, exit_price, exit_type, r_multiple = exit_row
            rows.append({
                "market": market,
                "strategy_id": "M15_SWEEP_FLIP",
                "setup_time": ts,
                "entry_time": m5.time.iloc[entry_idx],
                "exit_time": m5.time.iloc[k],
                "direction": direction,
                "entry": entry,
                "initial_sl": initial_sl,
                "tp": tp,
                "exit_price": exit_price,
                "exit_type": exit_type,
                "r_multiple": r_multiple,
                "bars_held": k-entry_idx+1,
                "mfe_r": mfe,
                "mae_r": mae,
                "trail_updates": trail_updates,
                "h1_bias": bias,
                "asian_high": asian_high,
                "asian_low": asian_low,
            })

        trades = pd.DataFrame(rows)
        return trades, self._summary(trades, market)

    def _summary(self, trades: pd.DataFrame, market: str) -> dict:
        if trades.empty:
            return {
                "market": market,
                "trades": 0,
                "starting_balance": self.starting_balance,
                "ending_balance": self.starting_balance,
            }

        rs = trades.r_multiple.astype(float)
        wins = int((rs > 0).sum())
        gross_win = float(rs[rs > 0].sum())
        gross_loss = abs(float(rs[rs < 0].sum()))
        pf = gross_win / gross_loss if gross_loss else math.inf
        eq_r = rs.cumsum()
        max_dd_r = abs(float((eq_r - eq_r.cummax()).min()))
        net_r = float(rs.sum())

        balance = self.starting_balance
        peak = balance
        max_cash_dd_pct = 0.0
        for r in rs:
            balance += balance * (self.risk_pct / 100.0) * float(r)
            peak = max(peak, balance)
            max_cash_dd_pct = max(
                max_cash_dd_pct,
                100.0 * (peak-balance) / peak,
            )

        return {
            "market": market,
            "trades": len(trades),
            "win_rate_pct": 100.0 * wins / len(trades),
            "profit_factor": pf,
            "net_r": net_r,
            "max_drawdown_r": max_dd_r,
            "recovery_factor": net_r / max_dd_r if max_dd_r else math.inf,
            "starting_balance": self.starting_balance,
            "ending_balance": balance,
            "return_pct": 100.0 * (balance/self.starting_balance - 1.0),
            "cash_max_dd_pct": max_cash_dd_pct,
            "median_duration_min": float(trades.bars_held.median() * 5),
            "trail_exit_pct": 100.0 * float((trades.exit_type == "TRAIL_SL").mean()),
        }
