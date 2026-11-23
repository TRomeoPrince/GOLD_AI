"""Regression tests for Pullback neutral detection and M15 executable entries.

Pure unit tests: never initialize MT5 or place orders.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import pandas as pd

from backtesting.engine import BacktestEngine
from strategies.base import StrategySignal
from strategies.execution_prices import target_at_executable_price
from strategies.pullback import PullbackStrategy


def signal(direction="BUY"):
    if direction == "BUY":
        sl, tp = 1990.0, 2020.0
    else:
        sl, tp = 2010.0, 1980.0
    return StrategySignal("M15_BREAKOUT", direction, "M15",
                          "2026-11-23T12:00:00+00:00", 2000.0, sl, tp,
                          "M15_RANGE_BREAK_RETEST_CONTINUATION",
                          {"reward_r": 2.0})


class PullbackRangeRegression(TestCase):
    def test_flat_window_never_counts_as_sell(self):
        t = pd.date_range("2026-11-23", periods=50, freq="5min", tz="UTC")
        candles = pd.DataFrame({
            "time": t, "open": [2000.1] * 50, "close": [2000.0] * 50,
            "high": [2000.2] * 50, "low": [1999.8] * 50,
        })
        self.assertEqual(PullbackStrategy().scan(candles), [])

    def test_choppy_window_is_neutral_even_if_net_negative(self):
        values = pd.Series([2000 + (0.4 if i % 2 else 0.0) - 0.01 * i
                            for i in range(12)])
        self.assertIsNone(PullbackStrategy()._trend_direction(values, 0.5))

    def test_clear_trends_still_have_explicit_direction(self):
        s = PullbackStrategy()
        up = pd.Series([2000 + 0.3 * i for i in range(12)])
        down = pd.Series([2000 - 0.3 * i for i in range(12)])
        self.assertEqual(s._trend_direction(up, 0.5), "UP")
        self.assertEqual(s._trend_direction(down, 0.5), "DOWN")


class M15ExecutionRegression(TestCase):
    def test_same_structural_stop_and_two_r_both_directions(self):
        self.assertAlmostEqual(target_at_executable_price("BUY", 2002, 1990, 2), 2026)
        self.assertAlmostEqual(target_at_executable_price("SELL", 1998, 2010, 2), 1974)
        for direction, price, stop in (("BUY", 1989, 1990), ("SELL", 2011, 2010)):
            with self.subTest(direction=direction), self.assertRaises(ValueError):
                target_at_executable_price(direction, price, stop, 2)

    def test_next_bar_open_not_m15_candle_close_and_costs(self):
        with TemporaryDirectory() as tmp:
            e = BacktestEngine(Path(tmp), point_size=.01, spread_points=15, slippage_points=5)
            bar = pd.Series({"open": 2002.0, "spread": 15, "high": 2100,
                             "low": 1900, "close": 2090})
            filled = e._m15_fill(signal(), bar)
            self.assertIsNotNone(filled)
            self.assertAlmostEqual(filled.entry, 2002.20)
            self.assertEqual(filled.stop_loss, 1990)
            self.assertAlmostEqual(filled.take_profit, 2026.6)
            bar["high"], bar["low"], bar["close"] = 9999, 1, 1
            self.assertAlmostEqual(e._m15_fill(signal(), bar).entry, 2002.20)

    def test_sell_fill_and_exit_spread(self):
        with TemporaryDirectory() as tmp:
            e = BacktestEngine(Path(tmp), point_size=.01, spread_points=30, slippage_points=5)
            bar = pd.Series({"open": 1999.0, "spread": 30})
            filled = e._m15_fill(signal("SELL"), bar)
            self.assertAlmostEqual(filled.entry, 1998.95)
            self.assertEqual(filled.stop_loss, 2010)
            self.assertAlmostEqual(filled.take_profit, 1976.85)
            # SELL SL is hit by ASK even when BID high is below the stop.
            bid_bars = pd.DataFrame([{"open": 2009.0, "high": 2009.8,
                                      "low": 2007.0, "close": 2008.0,
                                      "spread": 30}])
            result = e._resolve(filled, bid_bars)
            self.assertEqual(result[0], "SL")

    def test_gap_beyond_original_target_is_not_chased(self):
        with TemporaryDirectory() as tmp:
            e = BacktestEngine(Path(tmp))
            self.assertIsNone(e._m15_fill(signal(), pd.Series({"open": 2021.0})))
            self.assertIsNone(e._m15_fill(signal("SELL"), pd.Series({"open": 1979.0})))

    def test_run_uses_first_subsequent_m5_open_not_signal_reference(self):
        t = pd.date_range("2026-11-22", periods=105, freq="5min", tz="UTC")
        bars = pd.DataFrame({
            "time": t, "open": [2000.0] * 105, "high": [2001.0] * 105,
            "low": [1999.0] * 105, "close": [2000.0] * 105,
        })
        bars.loc[100, ["open", "high", "low", "close"]] = (2002.0, 2003.0, 2001.0, 2002.5)
        with TemporaryDirectory() as tmp, patch("backtesting.engine.StrategyRegistry") as registry:
            registry.return_value.models = [object()]
            registry.return_value.scan.return_value = [signal()]
            engine = BacktestEngine(Path(tmp), warmup_bars=100, max_hold_bars=2)
            trades, _, _ = engine.run(bars)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.loc[0, "entry"], 2002.0)
        self.assertEqual(trades.loc[0, "signal_reference_entry"], 2000.0)
        self.assertEqual(trades.loc[0, "take_profit"], 2026.0)

    def test_m15_fill_costs_are_not_deducted_twice(self):
        t = pd.date_range("2026-11-22", periods=105, freq="5min", tz="UTC")
        bars = pd.DataFrame({
            "time": t, "open": [2000.] * 105,
            "high": [2001.] * 105, "low": [1999.] * 105,
            "close": [2000.] * 105,
        })
        bars.loc[100, ["open", "high", "low", "close"]] = (2002., 2003., 2001., 2002.5)
        with TemporaryDirectory() as tmp, patch("backtesting.engine.StrategyRegistry") as registry:
            registry.return_value.models = [object()]
            registry.return_value.scan.return_value = [signal()]
            engine = BacktestEngine(Path(tmp), warmup_bars=100, max_hold_bars=2,
                                    spread_points=15, slippage_points=5,
                                    point_size=.01, commission_r=.1)
            trades, _, _ = engine.run(bars)
        self.assertEqual(len(trades), 1)
        self.assertAlmostEqual(trades.loc[0, "entry"], 2002.2)
        self.assertAlmostEqual(trades.loc[0, "cost_r"], .1)
        self.assertAlmostEqual(trades.loc[0, "r_multiple"],
                               trades.loc[0, "gross_r"] - .1)
