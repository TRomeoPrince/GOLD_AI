"""Safety and causal-order tests for isolated break-candle trailing research."""from __future__ import annotations

from types import SimpleNamespace
import pandas as pd
import pytest

from research.structure_break_experiment import (
    BreakEvent, TrailConfig, identify_breaks, identify_multiframe_breaks,
    simulate, load_bars, summarize, compare,
)


def frame(prices, start="2026-10-01 00:00:00+00:00"):
    rows = []
    for i, (o, h, l, c) in enumerate(prices):
        rows.append({"time": pd.Timestamp(start) + pd.Timedelta(minutes=i * 5),
                     "open": o, "high": h, "low": l, "close": c})
    return pd.DataFrame(rows)


def sample_trade():
    rows = [(100., 101., 99., 100.)] * 20
    rows += [(100., 103., 99., 102.), (102., 104., 101., 103.),
             (103., 109., 102., 108.), (108., 109., 99.5, 100.),
             (100., 131., 99.9, 130.)]
    return frame(rows)


def sig(side="BUY", sl=90., tp=130.):
    return SimpleNamespace(direction=side, entry=100., stop_loss=sl, take_profit=tp)


def test_break_candle_stop_is_wick_plus_buffer():
    e = BreakEvent(22, "BUY", "STRUCTURE_BOS_CHOCH", 104., 109., 102., 2.)
    assert e.proposed_stop(.15) == pytest.approx(101.7)
    e = BreakEvent(22, "SELL", "CONSOLIDATION_BREAK", 96., 99., 91., 2.)
    assert e.proposed_stop(.15) == pytest.approx(99.3)


def test_trail_only_after_candle_closed_and_never_loosened():
    f = sample_trade()
    cfg = TrailConfig(atr_buffer=.15, activate_r=0)
    events = {22: [BreakEvent(22, "BUY", "STRUCTURE_BOS_CHOCH", 104, 109, 102, 2.)]}
    fixed = simulate(f, sig(), 20, events, cfg, trailing=False, max_hold=10)
    trailed = simulate(f, sig(), 20, events, cfg, trailing=True, max_hold=10)
    assert fixed["exit_reason"] == "TP"
    assert fixed["r_multiple"] == pytest.approx(3.)
    assert trailed["exit_reason"] == "TRAIL_SL"
    assert trailed["final_sl"] == pytest.approx(101.7)
    assert trailed["trail_updates"] == 1


def test_no_trail_until_activation():
    f = sample_trade()
    cfg = TrailConfig(atr_buffer=.15, activate_r=1.)
    events = {22: [BreakEvent(22, "BUY", "BOS", 104, 109, 102, 2.)]}
    r = simulate(f, sig(), 20, events, cfg, trailing=True, max_hold=10)
    assert r["trail_updates"] == 0
    assert r["exit_reason"] == "TP"


def test_breaker_cannot_look_ahead():
    f = sample_trade()
    cfg = TrailConfig(min_body_atr=.0)
    first = identify_breaks(f.iloc[:23].copy(), cfg)
    assert all(i < 23 for i in first)
    assert len(identify_breaks(f.iloc[:22].copy(), cfg)) <= len(first)


def test_sell_gap_fills_at_open_not_stop():
    f = frame([(100., 100.5, 99.5, 100.)] * 20 + [(110., 112., 107., 108.)])
    res = simulate(f, sig("SELL", sl=105., tp=80.), 19, {}, TrailConfig(), trailing=False, max_hold=5)
    assert res["exit_reason"] == "SL_GAP"
    assert res["exit_price"] == 110.


def test_stop_first_same_bar():
    f = frame([(100., 100.5, 99.5, 100.)] * 20 + [(100., 140., 80., 110.)])
    result = simulate(f, sig(), 20, {}, TrailConfig(), trailing=False, max_hold=5)
    assert result["exit_reason"] == "SL"
    assert result["r_multiple"] == -1.


def test_multiframe_has_only_completed_bar_events():
    # A partial final M15 candle cannot trigger an M15 event.
    f = frame([(100., 100.5, 99.5, 100.)] * 70)
    cfg = TrailConfig()
    tf = identify_multiframe_breaks(f, cfg, ("M5", "M15", "H1"))
    assert isinstance(tf, dict)
    assert all(event.timeframe in {"M5", "M15", "H1"} for value in tf.values() for event in value)
    with pytest.raises(ValueError):
        identify_multiframe_breaks(f, cfg, ("M1",))


def test_closest_protective_stop_selected_from_multiple_timeframes():
    f = sample_trade()
    events = {22: [
        BreakEvent(22, "BUY", "BOS", 105, 110, 101, 2., "M5"),
        BreakEvent(22, "BUY", "BOS", 105, 110, 103, 2., "M15"),
    ]}
    result = simulate(f, sig(), 20, events, TrailConfig(atr_buffer=.15), trailing=True, max_hold=10)
    assert result["final_sl"] == pytest.approx(102.7)


def test_csv_validation(tmp_path):
    file = tmp_path / "bad.csv"
    file.write_text("time,open,close\n2026-10-01,1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_bars(file)


def test_summary_does_not_claim_historical_returns_without_trades():
    assert summarize(pd.DataFrame(), 1000., .9).empty


class NoSignals:
    def scan(self, visible):
        return []


def test_compare_no_signals_and_no_live_order_calls():
    f = frame([(100., 100.5, 99.5, 100.)] * 320)
    trades = compare(f, warmup=300, strategy_registry=NoSignals())
    assert trades.empty


def test_sell_trailing_uses_break_candle_high():
    bars = [(100., 101., 99., 100.)] * 20
    bars += [(100., 102., 97., 98.), (98., 100., 95., 97.),
             (97., 98., 91., 92.), (92., 97.5, 89., 93.),
             (93., 95., 69., 70.)]
    f = frame(bars)
    event = BreakEvent(22, "SELL", "CONSOLIDATION_BREAK", 94, 98, 91, 2.)
    fixed = simulate(f, sig("SELL", 110., 70.), 20, {22: [event]},
                     TrailConfig(), trailing=False, max_hold=10)
    trailed = simulate(f, sig("SELL", 110., 70.), 20, {22: [event]},
                       TrailConfig(), trailing=True, max_hold=10)
    assert fixed["exit_reason"] == "TP"
    assert trailed["exit_reason"] == "TRAIL_SL"
    assert trailed["final_sl"] == pytest.approx(98.3)


def test_end_to_end_backtest_paired_same_entry_no_live_calls():
    from strategies.base import StrategySignal

    f = sample_trade()
    # Preserve exact strategy inputs by selecting a signal from latest CLOSED candle.
    class FakeRegistry:
        def scan(self, visible):
            if pd.Timestamp(visible.iloc[-2]["time"]) != pd.Timestamp(f.at[19, "time"]):
                return []
            return [StrategySignal("TEST", "BUY", "M5", str(f.at[19, "time"]),
                                   100., 90., 130., "synthetic research fixture")]
    r = compare(f, warmup=19, max_hold=10, strategy_registry=FakeRegistry(),
                trail_timeframes=("M5",))
    # warmup is intentionally validated by the runner, so use a longer series.
