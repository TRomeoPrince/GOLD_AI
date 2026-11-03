"""AZT experimental S/R M5 confirmations + same-strategy direction lock.

Read-only OHLC backtest. Does not alter server signal registry, place trades,
change portfolio risk limits, or connect to live MT5.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from strategies.base import StrategySignal
from strategies.indicators import atr
from strategies.support_resistance import SupportResistanceStrategy

MODES = (
    "BASELINE",
    "CONFIRMATION_ONLY",
    "DIRECTION_LOCK_ONLY",
    "CONFIRMATION_AND_LOCK",
    "ENGULFING_ONLY",
    "ENGULFING_AND_LOCK",
)


class ConfirmedSupportResistance(SupportResistanceStrategy):
    """Alternative signal generation; ONLY use fully completed M5 candles.

    BUY: convincing resistance breakout OR support engulfing/rejection.
    SELL: convincing support breakdown OR resistance engulfing/rejection.
    No confirmation based solely on wicks crossing a level.
    """

    def scan(self, candles):
        if candles is None or len(candles) < 50:
            return []
        # The scanner convention in AZT: last row is the *forming* candle.
        f = candles.iloc[:-1].tail(self.lookback).copy().reset_index(drop=True)
        f["atr"] = atr(f, 14)
        if len(f) < 3:
            return []
        current, prev = f.iloc[-1], f.iloc[-2]
        a = float(current.atr) if pd.notna(current.atr) else 0
        if not a > 0:
            return []

        # Determine levels from bars completed PRIOR to the confirmation bar,
        # preventing the breakout candle from defining its own breakout level.
        old = f.iloc[:-1]
        highs, lows = self._pivots(old)
        resistance = self._level(highs, a * self.cluster_atr)
        support = self._level(lows, a * self.cluster_atr)

        op, high, low, close = map(float, (current.open, current.high, current.low, current.close))
        po, pc = float(prev.open), float(prev.close)
        body = abs(close - op)
        span = max(high - low, 1e-12)
        low_wick = min(close, op) - low
        high_wick = high - max(close, op)
        direction = "BUY" if close > op else "SELL" if close < op else None
        if direction is None:
            return []

        # 1. Closed strong candle actually clears clustered S/R.
        strong = body >= 0.35 * a
        bullish_break = (
            resistance is not None and direction == "BUY" and
            pc <= resistance and close > resistance + .15 * a and
            strong and high_wick / span <= .35
        )
        bearish_break = (
            support is not None and direction == "SELL" and
            pc >= support and close < support - .15 * a and
            strong and low_wick / span <= .35
        )

        # 2. Engulf the previous opposite-color real body AT the S/R zone.
        bullish_engulf = (
            support is not None and direction == "BUY" and po > pc and
            op <= pc and close >= po and
            low <= support + .25 * a and close > support + .03 * a
        )
        bearish_engulf = (
            resistance is not None and direction == "SELL" and po < pc and
            op >= pc and close <= po and
            high >= resistance - .25 * a and close < resistance - .03 * a
        )

        # 3. Real rejection must close away from level and show a long wick.
        bullish_reject = (
            support is not None and direction == "BUY" and
            low <= support + self.touch_atr * a and
            close > support + .08 * a and low_wick >= 1.2 * max(body, .12 * a)
            and (close - low) / span >= .65 and body >= .1 * a
        )
        bearish_reject = (
            resistance is not None and direction == "SELL" and
            high >= resistance - self.touch_atr * a and
            close < resistance - .08 * a and high_wick >= 1.2 * max(body, .12 * a)
            and (high - close) / span >= .65 and body >= .1 * a
        )

        if bullish_break or bullish_engulf or bullish_reject:
            kind = "BREAKOUT" if bullish_break else "ENGULFING" if bullish_engulf else "REJECTION"
            level = resistance if bullish_break else support
            sl = min(low, float(level)) - self.stop_atr * a
            sl = min(sl, close - self.min_stop_atr * a)
            r = close - sl
            if r > 0:
                return [StrategySignal(
                    self.strategy_id, "BUY", "M5", str(current.time), close, sl,
                    close + self.reward_r * r, "M5_CONFIRMED_" + kind,
                    {"level": level, "kind": kind, "atr": a},
                )]
        if bearish_break or bearish_engulf or bearish_reject:
            kind = "BREAKOUT" if bearish_break else "ENGULFING" if bearish_engulf else "REJECTION"
            level = support if bearish_break else resistance
            sl = max(high, float(level)) + self.stop_atr * a
            sl = max(sl, close + self.min_stop_atr * a)
            r = sl - close
            if r > 0:
                return [StrategySignal(
                    self.strategy_id, "SELL", "M5", str(current.time), close, sl,
                    close - self.reward_r * r, "M5_CONFIRMED_" + kind,
                    {"level": level, "kind": kind, "atr": a},
                )]
        return []


def load_bars(file: str | Path) -> pd.DataFrame:
    df = pd.read_csv(file)
    if "datetime" in df and "time" not in df:
        df = df.rename(columns={"datetime": "time"})
    cols = ("time", "open", "high", "low", "close")
    if not set(cols).issubset(df.columns):
        raise ValueError("Missing one of time,open,high,low,close")
    df = df.loc[:, list(cols)].copy()
    df["time"] = pd.to_datetime(df.time, utc=True, errors="raise")
    for col in cols[1:]:
        df[col] = pd.to_numeric(df[col], errors="raise")
    df = df.dropna().sort_values("time").drop_duplicates("time").reset_index(drop=True)
    if ((df.high < df[["open", "low", "close"]].max(axis=1)) |
        (df.low > df[["open", "high", "close"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC candle data.")
    return df


def close_trade(df: pd.DataFrame, signal: StrategySignal, entry_bar: int, *,
                hold: int, roundtrip_price_cost: float) -> dict | None:
    """Next-open fill; SL-first collision; gaps at observed open; no lookahead."""
    entry = float(df.at[entry_bar, "open"])
    sl = float(signal.stop_loss)
    risk = entry - sl if signal.direction == "BUY" else sl - entry
    if risk <= 0:
        return None
    # Preserve the exact TP provided by each strategy; the real executor
    # receives the strategy's fixed SL/TP and fills near the next opening price.
    target = float(signal.take_profit)
    if not (sl < entry < target if signal.direction == "BUY" else target < entry < sl):
        return None
    end = min(len(df), entry_bar + hold)
    exit_index = end - 1
    price = float(df.at[exit_index, "close"])
    result = "TIME"
    for j in range(entry_bar, end):
        b = df.iloc[j]
        op, hi, lo = map(float, (b.open, b.high, b.low))
        if signal.direction == "BUY":
            gap_stop, gap_tp = op <= sl, op >= target
            hit_sl, hit_tp = lo <= sl, hi >= target
        else:
            gap_stop, gap_tp = op >= sl, op <= target
            hit_sl, hit_tp = hi >= sl, lo <= target
        if gap_stop or gap_tp:
            price, exit_index, result = op, j, "SL_GAP" if gap_stop else "TP_GAP"
            break
        if hit_sl or hit_tp:
            price, exit_index, result = (sl if hit_sl else target), j, ("SL" if hit_sl else "TP")
            break
    gross = (price - entry) if signal.direction == "BUY" else (entry - price)
    net_r = (gross - roundtrip_price_cost) / risk
    return {
        "entry_index": entry_bar, "exit_index": exit_index,
        "entry_time": str(df.at[entry_bar, "time"]),
        "exit_time": str(df.at[exit_index, "time"]),
        "direction": signal.direction, "pattern": signal.reason,
        "entry": entry, "sl": sl, "tp": target,
        "exit_price": price, "exit_type": result,
        "initial_risk_price": risk, "net_r": net_r,
    }


def select_trades(df: pd.DataFrame, candidates: list[tuple[int, StrategySignal]],
                  *, max_hold: int, cost_price: float, direction_lock: bool):
    """Position-aware direction filter using known entry & simulated exit times.

    Opposite direction from the same strategy cannot enter while any older
    opposite-position is still open. Same direction is permitted. The exit
    bar counts as active because the intrabar order is unknown.
    """
    accepted = []
    rejected = 0
    for bar, signal in candidates:
        if direction_lock and any(
            x["exit_index"] >= bar and x["direction"] != signal.direction
            for x in accepted
        ):
            rejected += 1
            continue
        trade = close_trade(df, signal, bar, hold=max_hold, roundtrip_price_cost=cost_price)
        if trade is not None:
            accepted.append(trade)
    return accepted, rejected


def pairwise_backtest(df: pd.DataFrame, *, history_window=180, warmup=300,
                      max_hold=60, cost_price=.5) -> tuple[pd.DataFrame, pd.DataFrame]:
    if warmup < 80 or max_hold < 1 or cost_price < 0:
        raise ValueError("Bad test parameters.")
    models = {
        False: SupportResistanceStrategy(min_stop_atr=1.5),
        True: ConfirmedSupportResistance(min_stop_atr=1.5),
    }
    histories: dict[bool, list[tuple[int, StrategySignal]]] = {False: [], True: []}
    for k in range(warmup, len(df) - 1):
        history = df.iloc[max(0, k - history_window):k].copy()
        # Replace all contents of the current forming bar; current future
        # candle can NEVER provide high/low/close to the strategy.
        forming = df.iloc[k:k + 1].copy()
        for field in ("open", "high", "low", "close"):
            forming.loc[:, field] = float(history.iloc[-1].close)
        visible = pd.concat([history, forming], ignore_index=True)
        for enhanced, model in models.items():
            for signal in model.scan(visible):
                if pd.to_datetime(signal.setup_time, utc=True) != df.at[k - 1, "time"]:
                    continue
                histories[enhanced].append((k, signal))

    results = []
    summary_metadata = []
    for mode in MODES:
        confirmed = mode.startswith("CONFIRMATION") or mode.startswith("ENGULFING")
        locked = mode.endswith("LOCK") or mode == "DIRECTION_LOCK_ONLY"
        candidates = histories[confirmed]
        if mode.startswith("ENGULFING"):
            candidates = [(k,s) for k,s in candidates if s.reason == "M5_CONFIRMED_ENGULFING"]
        accepted, rejected_opposites = select_trades(
            df, candidates, max_hold=max_hold, cost_price=cost_price,
            direction_lock=locked,
        )
        # Each accepted result already contains its entry bar. The signal
        # timestamp comes from the last closed M5 candle, never future data.
        for outcome in accepted:
            outcome["mode"] = mode
            outcome["setup_time"] = str(df.at[outcome["entry_index"] - 1, "time"])
        results.extend(accepted)
        summary_metadata.append({"mode": mode, "candidates": len(candidates),
                                 "rejected_opposite": rejected_opposites,
                                 "invalid_fills": len(candidates) - rejected_opposites - len(accepted)})
    return pd.DataFrame(results), pd.DataFrame(summary_metadata)


def summarize(trades: pd.DataFrame, counts: pd.DataFrame, *, balance=2000., risk_pct=1.) -> pd.DataFrame:
    output=[]
    for c in counts.itertuples():
        g = trades[trades["mode"] == c.mode].sort_values(["entry_index", "direction"]) if not trades.empty else pd.DataFrame()
        values = g.net_r.astype(float) if not g.empty else pd.Series(dtype=float)
        starting = float(balance)
        running = peak = starting
        max_dd = 0.
        for v in values:
            running *= max(0., 1 + float(risk_pct) / 100 * v)
            peak = max(peak, running)
            max_dd = max(max_dd, 100 * (peak-running)/peak)
        pos = values[values > 0]
        neg = values[values < 0]
        output.append({
            "mode": c.mode, "signals_seen": c.candidates, "trades":len(values),
            "opposing_entries_blocked": c.rejected_opposite,
            "win_rate_pct":round(100 * len(pos) / len(values),2) if len(values) else 0,
            "net_r":round(float(values.sum()),3),
            "average_r":round(float(values.mean()),3) if len(values) else 0,
            "profit_factor":round(float(pos.sum()/-neg.sum()),3) if len(neg) else None,
            "max_dd_pct":round(max_dd,2),
            "ending_balance":round(running,2),
            "return_pct":round(100*(running/starting-1),2),
        })
    return pd.DataFrame(output)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--csv",required=True)
    parser.add_argument("--output",default="Reports/sr_m5_confirmation")
    parser.add_argument("--limit",type=int,default=12000)
    parser.add_argument("--warmup",type=int,default=300)
    parser.add_argument("--history",type=int,default=180)
    parser.add_argument("--max-hold",type=int,default=60)
    parser.add_argument("--cost-price",type=float,default=.5)
    parser.add_argument("--balance",type=float,default=2000.)
    parser.add_argument("--risk-pct",type=float,default=1.)
    args=parser.parse_args()
    df=load_bars(args.csv)
    if args.limit:
        df=df.tail(args.limit).reset_index(drop=True)
    if len(df)<args.warmup+150:
        raise RuntimeError("Insufficient historical M5 candles.")
    trades,metadata=pairwise_backtest(df,history_window=args.history,warmup=args.warmup,
                                      max_hold=args.max_hold,cost_price=args.cost_price)
    summary=summarize(trades,metadata,balance=args.balance,risk_pct=args.risk_pct)
    dest=Path(args.output)
    dest.mkdir(parents=True,exist_ok=True)
    trades.to_csv(dest/"sr_trades.csv",index=False)
    summary.to_csv(dest/"sr_summary.csv",index=False)
    metadata.to_csv(dest/"sr_counts.csv",index=False)
    print(f"REAL OHLC M5 input: {len(df)} bars {df.time.min()} to {df.time.max()}")
    print("No MT5 order sends. All entries at next M5 open. Each trade SL-first.")
    print(f"Round-trip fixed price cost={args.cost_price}, nominal risk={args.risk_pct}% of evolving balance")
    print(summary.to_string(index=False))
    if not trades.empty:
        t=trades[trades["mode"]=="CONFIRMATION_AND_LOCK"]
        print("CONFIRMED PATTERNS (not separate optimizations):")
        print(t.groupby("pattern").agg(trades=("net_r","size"),net_r=("net_r","sum"),
                                       win_rate=("net_r",lambda s:round(float((s>0).mean())*100,2))).to_string())
    print("These are modelled results, not a live broker or daily 10-20% profit forecast.")


if __name__=="__main__":
    main()
