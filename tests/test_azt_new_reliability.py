"""AZT repair regression tests: no real MT5, HTTP provider, or trading."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

import pandas as pd

from server import store, azt_store as business, usd_news
from strategies.support_resistance import SupportResistanceStrategy
from backtesting.engine import BacktestEngine


class ReservationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db_patch = patch.object(store, "DB_PATH", Path(self.temp.name) / "test.db")
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.client, _ = store.create_client("Reliability Test")
        self.account = business.authorize_account(self.client.id, 123, "TestBroker")
        self.since = business.utc_iso(business.utc_now() - timedelta(minutes=40))

    def test_lost_response_expires_once_and_next_signal_survives(self):
        store.enqueue_instruction(self.client.id, "old-signal", "{}")
        old = business.next_account_instruction(self.client.id, self.account["id"], self.since)
        self.assertIsNotNone(old)
        store.enqueue_instruction(self.client.id, "fresh-signal", "{}")
        past = business.utc_iso(business.utc_now() - timedelta(minutes=21))
        with store.connect() as con:
            con.execute("UPDATE instructions SET created_utc=? WHERE id=?", (past, old["id"]))
            con.execute("UPDATE account_instruction_deliveries SET dispatched_utc=? WHERE instruction_id=?", (past, old["id"]))
        fresh = business.next_account_instruction(self.client.id, self.account["id"], self.since)
        self.assertIsNotNone(fresh)
        self.assertEqual(fresh["signal_key"], "fresh-signal")
        history = {row["instruction_id"]: row for row in business.instruction_deliveries(self.client.id)}
        self.assertEqual(history[old["id"]]["status"], "EXPIRED_UNCONFIRMED")
        self.assertEqual(business.acknowledge_account_instruction(
            self.client.id, self.account["id"], old["id"], "EXECUTED", "ticket=123",
            return_status=True), "ALREADY_FINAL")
        self.assertEqual(len([e for e in business.system_events()
                              if e["kind"] == "LATE_EXECUTION_ACK"]), 1)
        self.assertIsNone(business.next_account_instruction(self.client.id, self.account["id"], self.since))

    def test_final_conflicting_ack_does_not_overwrite_or_reopen(self):
        store.enqueue_instruction(self.client.id, "exactly-once", "{}")
        row = business.next_account_instruction(self.client.id, self.account["id"], self.since)
        self.assertEqual(business.acknowledge_account_instruction(
            self.client.id, self.account["id"], row["id"], "EXECUTED", "ticket=111",
            return_status=True), "ACKNOWLEDGED")
        self.assertEqual(business.acknowledge_account_instruction(
            self.client.id, self.account["id"], row["id"], "REJECTED", "late",
            return_status=True), "ALREADY_FINAL")
        history = business.instruction_deliveries(self.client.id)
        self.assertEqual(history[0]["status"], "EXECUTED")


class NewsGuardTests(unittest.TestCase):
    def test_usd_high_impact_only_and_inclusive_twenty_minute_window(self):
        event = {"country": "USD", "impact": "High", "title": "Core CPI",
                 "date": "2026-11-25T08:30:00-05:00"}
        other = {"country": "EUR", "impact": "High", "title": "ECB", "date": event["date"]}
        low = {"country": "USD", "impact": "Medium", "title": "PMI", "date": event["date"]}
        events = usd_news._parse_events([event,other,low])
        self.assertEqual(len(events), 1)
        instant = events[0][0]
        with patch.object(usd_news, "_download", return_value=events), \
             patch.object(usd_news, "_next_check", 0.0), \
             patch.object(usd_news, "_fetched_monotonic", None), \
             patch.object(usd_news, "_events", ()):
            self.assertTrue(usd_news.block_status(instant - timedelta(minutes=20))[0])
            self.assertTrue(usd_news.block_status(instant + timedelta(minutes=20))[0])
            self.assertFalse(usd_news.block_status(instant + timedelta(minutes=21))[0])

    def test_unavailable_calendar_blocks_new_entries_not_accounts(self):
        with patch.object(usd_news, "_download", side_effect=OSError("offline")), \
             patch.object(usd_news, "_next_check", 0.0), \
             patch.object(usd_news, "_fetched_monotonic", None), \
             patch.object(usd_news, "_events", ()):
            blocked, reason = usd_news.block_status(datetime.now(timezone.utc))
        self.assertTrue(blocked)
        self.assertIn("UNAVAILABLE", reason)


def candles_with_reactions(two_history=False, engulf=False):
    data = []
    for i in range(81):
        op, high, low, close = 102.5, 103.0, 102.0, 102.5
        if i == 10 or (two_history and i == 30):
            low = 100.0
        if engulf and i == 78:
            op, high, low, close = 102.2, 102.5, 100.0, 101.0
        elif i == 79:
            if engulf:
                op, high, low, close = 100.8, 103.0, 100.6, 102.7
            else:
                op, high, low, close = 102.2, 103.0, 100.0, 102.6
        data.append({"time":i,"open":op,"high":high,"low":low,"close":close})
    return pd.DataFrame(data)


class SupportResistanceTests(unittest.TestCase):
    def test_two_touch_and_three_touch_modes_are_independent(self):
        bars = candles_with_reactions()
        with patch("strategies.support_resistance.atr",
                   side_effect=lambda f, _: pd.Series([1.0] * len(f))):
            two = SupportResistanceStrategy(min_touches=2).scan(bars)
            three = SupportResistanceStrategy(min_touches=3).scan(bars)
        self.assertEqual(len(two), 1)
        self.assertEqual(two[0].direction, "BUY")
        self.assertEqual(two[0].features["total_touches"], 2)
        self.assertEqual(three, [])

    def test_engulfing_after_level_reaction_is_valid(self):
        bars = candles_with_reactions(engulf=True)
        with patch("strategies.support_resistance.atr",
                   side_effect=lambda f, _: pd.Series([1.0] * len(f))):
            signals = SupportResistanceStrategy(min_touches=2).scan(bars)
        self.assertEqual(len(signals), 1)
        self.assertIn("ENGULFING_AFTER_REACTION", signals[0].reason)

    def test_backtest_loads_market_models_and_accounts_for_costs(self):
        with tempfile.TemporaryDirectory() as folder:
            test = BacktestEngine(Path(folder), market="XAUUSD",
                                  strategy_ids=("SUPPORT_RESISTANCE",),
                                  sr_options={"min_touches": 3},
                                  point_size=0.01, spread_points=30,
                                  slippage_points=10, commission_r=0.03)
            self.assertGreater(len(__import__("strategies").StrategyRegistry("GOLD").models), 0)
            self.assertEqual(test.market, "XAUUSD")
            self.assertEqual(test.sr_options["min_touches"], 3)
            self.assertAlmostEqual(test.commission_r, 0.03)


if __name__ == "__main__":
    unittest.main()
