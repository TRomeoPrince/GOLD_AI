"""Isolated historical comparison; never sends orders or edits production trailing.

Use identical entry signals for FIXED and BREAK_CANDLE modes.
Execution is deliberately conservative: next-bar entry, closed-bar-only signals,
stop-first when both SL and TP touch, and stop-gap fills at the next open.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class TrailConfig:
    pivot_span: int = 2
    pivot_lookback: int = 80
    range_bars: int = 6
    range_max_atr: float = 3.0
    min_body_atr: float = 0.35
    atr_buffer: float = 0.15
    activate_r: float = 0.0


@dataclass(frozen=True)
class BreakEvent:
    bar_index: int
    direction: str
    kind: str
    level: float
    break_high: float
    break_low: float
    atr: float

    def proposed_stop(self, buffer_atr: float) -> float:
        buffer = max(0.0, buffer_atr) * self.atr
        return self.break_low - buffer if self.direction == "BUY" else self.break_high + buffer


def load_bars(path: str | Path) -> pd.DataFrame:
    f = pd.read_csv(path)
    needed = {"time", "open", "high", "low", "close"}
    if not needed.issubset(f.columns):
        raise ValueError("CSV requires time,open,high,low,close (UTC times).")
    f = f.copy()
    f["time"] = pd.to_datetime(f["time"], utc=True, errors="raise")
    for col in ("open", "high", "low", "close"):
        f[col] = pd.to_numeric(f[col], errors="raise")
    f = f.dropna(subset=list(needed)).sort_values("time").drop_duplicates("time")
    if not f["time"].is_monotonic_increasing:
        raise ValueError("Bar times must be increasing.")
    if (f["high"] < f[["open", "close", "low"]].max(axis=1)).any() or (
        f["low"] > f[["open", "close", "high"]].min(axis=1)
    ).any():
        raise ValueError("Malformed OHLC candle.")
    return f.reset_index(drop=True)


def _last_pivot(f: pd.DataFrame, end: int, side: str, span: int, lookback: int):
    """Return a pivot confirmed before breaker at 'end' (no future bars)."""
    name = "high" if side == "BUY" else "low"
    first = max(span, end - lookback)
    for i in range(end - span - 1, first - 1, -1):
        value = float(f.at[i, name])
        window = f.iloc[i - span:i + span + 1][name]
        if side == "BUY" and value >= float(window.max()):
            return value
        if side == "SELL" and value <= float(window.min()):
            return value
    return None


def identify_breaks(f: pd.DataFrame, cfg: TrailConfig) -> dict[int, BreakEvent]:
    """A break is recognized on close; any SL adjustment starts NEXT bar."""
    if cfg.pivot_span < 1 or cfg.range_bars < 2:
        raise ValueError("pivot_span and range_bars are invalid.")
    if cfg.atr_buffer < 0 or cfg.activate_r < 0:
        raise ValueError("Trailing buffer/activation cannot be negative.")
    h, l, c = f["high"], f["low"], f["close"]
    previous = c.shift(1)
    true_range = pd.concat([(h - l), (h - previous).abs(), (l - previous).abs()], axis=1).max(axis=1)
    atr = true_range.rolling(14, min_periods=14).mean()
    events: dict[int, BreakEvent] = {}
    min_bars = max(15, cfg.range_bars + 1, cfg.pivot_span * 2 + 2)
    for k in range(min_bars, len(f)):
        a = float(atr.iloc[k])
        if not (a > 0):
            continue
        row = f.iloc[k]
        op, cl, prev = float(row.open), float(row.close), float(f.iloc[k - 1].close)
        if abs(cl - op) < cfg.min_body_atr * a:
            continue
        direction = "BUY" if cl > op else "SELL"
        pivot = _last_pivot(f, k, direction, cfg.pivot_span, cfg.pivot_lookback)
        if pivot is not None:
            broke = (prev <= pivot < cl) if direction == "BUY" else (prev >= pivot > cl)
            if broke:
                events[k] = BreakEvent(k, direction, "STRUCTURE_BOS_CHOCH", pivot,
                                       float(row.high), float(row.low), a)
                continue
        base = f.iloc[k - cfg.range_bars:k]
        width = float(base.high.max() - base.low.min())
        if width > cfg.range_max_atr * a:
            continue
        level = float(base.high.max()) if direction == "BUY" else float(base.low.min())
        crossed = (prev <= level < cl) if direction == "BUY" else (prev >= level > cl)
        if crossed:
            events[k] = BreakEvent(k, direction, "CONSOLIDATION_BREAK", level,
                                   float(row.high), float(row.low), a)
    return events


def simulate(
    f: pd.DataFrame, signal, first_bar: int, events: dict[int, BreakEvent],
    cfg: TrailConfig, *, trailing: bool, max_hold: int, cost_price: float = 0.0,
):
    """OHLC simulator. Neither setup nor stop changes can inspect future bars."""
    side = signal.direction
    entry = float(f.at[first_bar, "open"])
    stop = float(signal.stop_loss)
    target = float(signal.take_profit)
    valid = stop < entry < target if side == "BUY" else target < entry < stop
    if not valid:
        return None
    initial_risk = abs(entry - stop)
    changes = 0
    last = min(len(f), first_bar + max_hold)
    if last <= first_bar or initial_risk <= 0:
        return None
    end_kind, exit_price, held = "TIME", float(f.at[last - 1, "close"]), last - first_bar
    for k in range(first_bar, last):
        bar = f.iloc[k]
        op, hi, lo, cl = (float(bar[x]) for x in ("open", "high", "low", "close"))
        # Overnight gaps at the open precede stop-management decisions.
        gap_stop = op <= stop if side == "BUY" else op >= stop
        gap_target = op >= target if side == "BUY" else op <= target
        if gap_stop or gap_target:
            end_kind, exit_price, held = ("SL_GAP" if gap_stop else "TP_GAP"), op, k - first_bar + 1
            break
        # A completed breaker may change SL only from the NEXT bar open onward.
        if trailing and k > first_bar:
            event = events.get(k - 1)
            if event is not None and event.direction == side:
                previous_close = float(f.at[k - 1, "close"])
                favorable = previous_close - entry if side == "BUY" else entry - previous_close
                if favorable / initial_risk >= cfg.activate_r:
                    proposed = event.proposed_stop(cfg.atr_buffer)
                    improves = (stop < proposed < op) if side == "BUY" else (op < proposed < stop)
                    if improves:
                        stop = proposed
                        changes += 1
        hit_sl = lo <= stop if side == "BUY" else hi >= stop
        hit_tp = hi >= target if side == "BUY" else lo <= target
        if hit_sl or hit_tp:
            # Stop first if a single candle spans both levels; conservative.
            end_kind, exit_price, held = ("TRAIL_SL" if trailing and changes else "SL", stop, k - first_bar + 1) if hit_sl else ("TP", target, k - first_bar + 1)
            break
    directional = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    net_r = (directional - cost_price) / initial_risk
    return {
        "entry": entry, "initial_sl": float(signal.stop_loss),
        "final_sl": stop, "tp": target, "exit_price": exit_price,
        "exit_reason": end_kind, "bars_held": held, "trail_updates": changes,
        "r_multiple": net_r, "initial_risk_price": initial_risk,
    }


def compare(
    f: pd.DataFrame, *, market: str = "GOLD", warmup: int = 300,
    history_window: int = 600, max_hold: int = 60,
    cfg: TrailConfig = TrailConfig(), cost_price: float = 0,
    strategy_registry=None,
) -> pd.DataFrame:
    if cost_price < 0 or max_hold < 1 or warmup < 30:
        raise ValueError("Invalid backtest settings.")
    if strategy_registry is None:
        from strategies.registry import StrategyRegistry
        strategy_registry = StrategyRegistry(market=market)
    events = identify_breaks(f, cfg)
    seen: set[tuple] = set()
    rows = []
    for i in range(warmup, len(f)):
        # The current forming candle is intentionally a dummy; its high/low/
        # close from the future NEVER enter a strategy scanner.
        history = f.iloc[max(0, i - history_window):i].copy()
        if history.empty:
            continue
        forming = f.iloc[i:i + 1].copy()
        known = float(history.iloc[-1]["close"])
        for field in ("open", "high", "low", "close"):
            forming.loc[:, field] = known
        visible = pd.concat([history, forming], ignore_index=True)
        last_closed = f.at[i - 1, "time"]
        open_time = f.at[i, "time"]
        for s in strategy_registry.scan(visible):
            when = pd.to_datetime(s.setup_time, utc=True)
            # Strict: no historical rediscovery, no future timestamps.
            if when < last_closed - pd.Timedelta(minutes=15) or when > open_time:
                continue
            key = (s.strategy_id, s.direction, str(when), float(s.stop_loss), float(s.take_profit))
            if key in seen:
                continue
            seen.add(key)
            for mode in ("FIXED", "BREAK_CANDLE"):
                result = simulate(f, s, i, events, cfg, trailing=(mode == "BREAK_CANDLE"),
                                  max_hold=max_hold, cost_price=cost_price)
                if result is None:
                    continue
                rows.append({
                    "trade_id": "|".join(map(str, key)),
                    "market": market, "strategy_id": s.strategy_id,
                    "direction": s.direction, "setup_time": str(when),
                    "entry_time": str(open_time), "mode": mode,
                    **result,
                })
    return pd.DataFrame(rows)


def summarize(trades: pd.DataFrame, starting_balance: float, risk_pct: float) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    if starting_balance <= 0 or not (0 < risk_pct <= 2):
        raise ValueError("Invalid balance/risk.")
    results = []
    for (mode, strategy), group in trades.groupby(["mode", "strategy_id"], sort=True):
        g = group.sort_values(["entry_time", "trade_id"])
        rs = g["r_multiple"].astype(float)
        balance = peak = starting_balance
        max_drawdown_pct = 0.0
        for r in rs:
            balance *= (1 + risk_pct / 100 * r)
            peak = max(peak, balance)
            max_drawdown_pct = max(max_drawdown_pct, 100 * (peak - balance) / peak)
        wins, losses = rs[rs > 0], rs[rs < 0]
        results.append({
            "mode": mode, "strategy_id": strategy, "trades": len(rs),
            "win_rate_pct": round(100 * len(wins) / len(rs), 2),
            "net_r": round(float(rs.sum()), 4),
            "avg_r": round(float(rs.mean()), 4),
            "profit_factor": round(float(wins.sum() / -losses.sum()), 4) if len(losses) else None,
            "max_drawdown_pct": round(max_drawdown_pct, 3),
            "ending_balance": round(balance, 2),
            "return_pct": round(100 * (balance / starting_balance - 1), 3),
            "trail_updates": int(g["trail_updates"].sum()),
        })
    return pd.DataFrame(results)


def get_mt5_data(bars: int, symbol: str) -> pd.DataFrame:
    """Read only: uses existing selected terminal, makes NO trade requests."""
    import MetaTrader5 as mt5
    from broker.mt5_client import MT5Client
    conn = MT5Client(symbol)
    try:
        conn.connect()
        return conn.candles(mt5.TIMEFRAME_M5, bars)
    finally:
        conn.shutdown()


def main():
    p = argparse.ArgumentParser(description="AZT isolated structure-break trailing research; NO live trading")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="UTC OHLC M5 CSV")
    source.add_argument("--mt5-bars", type=int, help="Read historical M5 bars from currently open MT5 (read-only)")
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--market", default="GOLD")
    p.add_argument("--output", default="Reports/structure_break_trail")
    p.add_argument("--warmup", type=int, default=300)
    p.add_argument("--history-window", type=int, default=600)
    p.add_argument("--max-hold", type=int, default=60)
    p.add_argument("--activate-r", type=float, default=0.0)
    p.add_argument("--buffer-atr", type=float, default=0.15)
    p.add_argument("--cost-price", type=float, default=0.0,
                   help="Explicit round-trip price cost; 0 means gross results, NOT cost-adjusted")
    p.add_argument("--balance", type=float, default=1000)
    p.add_argument("--risk-pct", type=float, default=0.9)
    args = p.parse_args()
    cfg = TrailConfig(activate_r=args.activate_r, atr_buffer=args.buffer_atr)
    data = get_mt5_data(args.mt5_bars, args.symbol) if args.mt5_bars else load_bars(args.csv)
    trades = compare(data, market=args.market, warmup=args.warmup,
                     history_window=args.history_window, max_hold=args.max_hold,
                     cfg=cfg, cost_price=args.cost_price)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out / "paired_trades.csv", index=False)
    summary = summarize(trades, args.balance, args.risk_pct)
    summary.to_csv(out / "summary.csv", index=False)
    if not trades.empty:
        paired = trades.pivot_table(index="trade_id", columns="mode", values="r_multiple", aggfunc="first").dropna()
        paired["delta_r"] = paired["BREAK_CANDLE"] - paired["FIXED"]
        paired.to_csv(out / "paired_deltas.csv")
        print("Paired trades:", len(paired), "Net delta R:", round(float(paired.delta_r.sum()), 4))
    print("Actual M5 candles:", len(data), "Source:", "MT5" if args.mt5_bars else args.csv)
    print("Cost: ", args.cost_price, "(price units, round trip; zero = GROSS only)")
    print(summary.to_string(index=False) if not summary.empty else "No qualified signals.")
    print("Reports:", out.resolve())
    print("No orders submitted. Fixed and structure-trail cases use identical entries.")


if __name__ == "__main__":
    main()
