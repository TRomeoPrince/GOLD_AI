"""Telegram telemetry enrichments use fake MT5 and temporary databases only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from server import trade_telemetry as telemetry


BASE = "2026-10-28T00:00:00+00:00"
LATER = "2026-10-28T00:01:00+00:00"
LATEST = "2026-10-28T00:02:00+00:00"
KEY = "Broker|123"


class TelegramTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name, "telemetry.sqlite3"))

    def position(self, **changes):
        return dict(ticket="41", position_id="41", symbol="XAUUSD.c", direction="SELL",
                    strategy="PULLBACK", volume=.03, entry=4062.22, current_price=4061.91,
                    sl=4067.34, tp=4054.81, pnl=.93, sl_pnl=-15.36, tp_pnl=22.23,
                    opened_utc=BASE, **changes)

    def snapshot(self, observed=BASE, positions=None, currency="USC", trades=None):
        return {"observed_utc": observed,
                "account": {"login": 123, "server": "Broker", "currency": currency,
                            "balance": 1000, "equity": 1001, "password": "NEVER_PERSIST"},
                "positions": [self.position()] if positions is None else positions,
                "trades": trades or []}

    def ingest(self, snapshot, client_id=None):
        return telemetry.ingest_snapshot(client_id, KEY, snapshot, database=self.database)

    def api(self):
        api = Mock()
        api.POSITION_TYPE_BUY = 0
        api.ORDER_TYPE_BUY, api.ORDER_TYPE_SELL = 0, 1
        api.account_info.return_value = NS(login=123, server="Broker", currency="USC", balance=1000,
                                            equity=1001, margin=10, margin_free=991)
        api.terminal_info.return_value = NS(connected=True)
        raw_time = datetime(2026, 10, 28, 3, tzinfo=timezone.utc).timestamp()
        api.positions_get.return_value = [NS(ticket=41, symbol="XAUUSD.c", type=1, volume=.03,
            price_open=4062.22, price_current=4061.91, sl=4067.34, tp=4054.81,
            profit=.93, swap=-.04, comment="AZT:PULLBACK", time=raw_time)]
        api.history_deals_get.return_value = []
        api.order_calc_profit.side_effect = lambda side, symbol, volume, entry, price: (entry-price)*volume*100
        return api

    def test_capture_uses_actual_entry_and_read_only_native_currency_estimates(self):
        api = self.api()
        snapshot = telemetry.capture_mt5(api, clock_offset_seconds=10800)
        row = snapshot["positions"][0]
        self.assertEqual(row["opened_utc"], BASE)
        self.assertAlmostEqual(row["sl_pnl"], -15.36)
        self.assertAlmostEqual(row["tp_pnl"], 22.23)
        self.assertEqual(row["entry_basis"], "ACTUAL_FILL")
        self.assertAlmostEqual(row["pnl"], .89)
        self.assertEqual(snapshot["account"]["currency"], "USC")
        api.order_calc_profit.assert_any_call(1, "XAUUSD.c", .03, 4062.22, 4067.34)
        api.order_send.assert_not_called()
        api.initialize.assert_not_called()
        self.ingest(snapshot)
        stored = telemetry.list_trades(database=self.database)[0]
        self.assertAlmostEqual(stored["sl_pnl"], -15.36)
        self.assertEqual(stored["currency"], "USC")

    def test_unavailable_or_invalid_cash_estimate_is_unavailable(self):
        for result in (None, float("nan"), float("inf"), "bad"):
            with self.subTest(result=result):
                api = self.api()
                api.order_calc_profit.side_effect = None
                api.order_calc_profit.return_value = result
                api.positions_get.return_value[0].sl = 0
                row = telemetry.capture_mt5(api)["positions"][0]
                self.assertIsNone(row["sl_pnl"])
                self.assertIsNone(row["tp_pnl"])
                self.assertEqual(api.order_calc_profit.call_count, 1)
                api.order_send.assert_not_called()

    def test_execution_details_allowlist_and_exact_position_identity(self):
        details = {"entry": 4062.22, "entry_basis": "ACTUAL_FILL", "risk_cash": 15.36,
                   "portfolio_after_pct": 5.117, "max_open_risk_pct": 40,
                   "executed_utc": "2026-10-28T03:00:00+03:00", "currency": "USC",
                   "password": "NEVER_PERSIST", "token": "NEVER_PERSIST"}
        telemetry.record_execution(None, KEY, "41", {"strategy_id": "PULLBACK"},
                                   risk_pct=.879, trade_details=details, database=self.database)
        row = self.position()
        row.update(entry=None, strategy="—")
        other = self.position()
        other.update(ticket="99", position_id="99", risk_cash=None, strategy="—")
        self.ingest(self.snapshot(positions=[row, other]))
        stored = {item["ticket"]: item for item in telemetry.list_trades(database=self.database)}
        self.assertEqual(stored["41"]["strategy"], "PULLBACK")
        self.assertEqual(stored["41"]["risk_cash"], 15.36)
        self.assertEqual(stored["41"]["portfolio_after_pct"], 5.117)
        self.assertEqual(stored["41"]["max_open_risk_pct"], 40)
        self.assertEqual(stored["41"]["entry_basis"], "ACTUAL_FILL")
        self.assertEqual(stored["41"]["executed_utc"], BASE)
        self.assertIsNone(stored["99"]["risk_cash"])
        self.assertEqual(stored["99"]["strategy"], "—")
        with closing(sqlite3.connect(self.database)) as con, con:
            saved = con.execute("SELECT details_json FROM azt_execution_details").fetchone()[0]
            self.assertNotIn("NEVER_PERSIST", saved)
            self.assertNotIn("password", saved)

    def test_first_snapshot_silent_then_actual_same_ticket_sl_change(self):
        self.assertEqual(self.ingest(self.snapshot())["new_stop_updates"], [])
        updated = self.position()
        updated.update(sl=4060.22, sl_pnl=6)
        result = self.ingest(self.snapshot(LATER, [updated]))
        event, = result["new_stop_updates"]
        self.assertEqual(event["state"], "SL_UPDATED")
        self.assertEqual(event["old_sl"], 4067.34)
        self.assertEqual(event["new_sl"], 4060.22)
        self.assertEqual(event["sl"], event["new_sl"])
        self.assertEqual(event["old_sl_pnl"], -15.36)
        self.assertEqual(event["new_sl_pnl"], 6)
        self.assertEqual(event["currency"], "USC")
        self.assertEqual(event["account_key"], KEY)
        self.assertEqual(event["observed_utc"], LATER)
        self.assertEqual(event["change_source"], "OBSERVED")
        self.assertFalse(event["trailing_confirmed"])
        self.assertEqual(telemetry.list_stop_updates(database=self.database), [event])

    def test_new_or_reappearing_position_does_not_create_stop_change(self):
        self.ingest(self.snapshot())
        row = self.position()
        row.update(ticket="99", position_id="99", sl=4060.22, opened_utc=LATER)
        result = self.ingest(self.snapshot(LATER, [row]))
        self.assertEqual(len(result["new_open"]), 1)
        self.assertEqual(result["new_stop_updates"], [])
        result = self.ingest(self.snapshot(LATEST, [self.position()]))
        self.assertEqual(result["new_stop_updates"], [])

    def test_concurrent_repeated_snapshots_emit_one_durable_event(self):
        self.ingest(self.snapshot())
        updated = self.position()
        updated.update(sl=4060.22, sl_pnl=6)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.ingest(self.snapshot(LATER, [updated])), range(2)))
        self.assertEqual(sum(len(result["new_stop_updates"]) for result in results), 1)
        saved = telemetry.list_stop_updates(database=self.database)
        self.assertEqual(len(saved), 1)
        self.assertEqual(self.ingest(self.snapshot(LATER, [updated]))["new_stop_updates"], [])
        self.assertEqual(telemetry.list_stop_updates(database=self.database)[0]["event_key"], saved[0]["event_key"])

    def test_stale_invalid_and_equal_timestamp_snapshots_cannot_move_baseline(self):
        self.ingest(self.snapshot(LATER))
        changed = self.position()
        changed.update(sl=4060.22, sl_pnl=6)
        for observed in (BASE, LATER):
            result = self.ingest(self.snapshot(observed, [changed]))
            self.assertFalse(result["accepted"])
            self.assertEqual(result["new_stop_updates"], [])
        changed["sl"] = float("nan")
        with self.assertRaises(ValueError):
            self.ingest(self.snapshot(LATEST, [changed]))
        self.assertEqual(telemetry.list_trades(database=self.database)[0]["sl"], 4067.34)
        self.assertEqual(telemetry.list_stop_updates(database=self.database), [])

    def test_setting_or_removing_sl_is_never_claimed_to_be_trailing(self):
        unset = self.position()
        unset.update(sl=0, sl_pnl=None)
        self.ingest(self.snapshot(positions=[unset]))
        event, = self.ingest(self.snapshot(LATER))["new_stop_updates"]
        self.assertFalse(event["trailing_confirmed"])
        self.assertIsNone(event["old_sl_pnl"])
        event, = self.ingest(self.snapshot(LATEST, [unset]))["new_stop_updates"]
        self.assertIsNone(event["new_sl_pnl"])
        self.assertEqual(event["new_sl"], 0)

    def test_external_observer_baseline_and_same_event_deduplication(self):
        self.ingest(self.snapshot())
        self.assertEqual(telemetry.observe_stored_stop_updates(database=self.database), [])
        changed = self.position()
        changed.update(sl=4060.22, sl_pnl=6)
        event, = self.ingest(self.snapshot(LATER, [changed]))["new_stop_updates"]
        self.assertEqual(telemetry.observe_stored_stop_updates(database=self.database), [])
        self.assertEqual(telemetry.list_stop_updates(database=self.database), [event])
        self.assertEqual(telemetry.observe_stored_stop_updates(database=self.database), [])

    def test_external_observer_can_observe_older_producer_rows(self):
        self.ingest(self.snapshot())
        telemetry.observe_stored_stop_updates(database=self.database)
        # Simulate the older producer's actual persisted snapshot without invoking
        # a new producer's automatic observation/event creation.
        with closing(sqlite3.connect(self.database)) as con, con:
            payload = json.loads(con.execute("SELECT payload_json FROM azt_trades").fetchone()[0])
            payload.update(sl=4060.22, sl_pnl=None)
            con.execute("UPDATE azt_trades SET payload_json=?,observed_utc=?", (json.dumps(payload), LATER))
            con.execute("UPDATE azt_account_snapshots SET observed_utc=?", (LATER,))
        event, = telemetry.observe_stored_stop_updates(database=self.database)
        self.assertEqual(event["old_sl"], 4067.34)
        self.assertEqual(event["new_sl"], 4060.22)
        self.assertIsNone(event["new_sl_pnl"])
        self.assertEqual(telemetry.observe_stored_stop_updates(database=self.database), [])

    def test_external_observer_does_not_duplicate_change_after_unchanged_snapshot(self):
        self.ingest(self.snapshot())
        telemetry.observe_stored_stop_updates(database=self.database)
        changed = self.position()
        changed.update(sl=4060.22, sl_pnl=6)
        event, = self.ingest(self.snapshot(LATER, [changed]))['new_stop_updates']
        self.assertEqual(self.ingest(self.snapshot(LATEST, [changed]))['new_stop_updates'], [])
        self.assertEqual(telemetry.observe_stored_stop_updates(database=self.database), [])
        self.assertEqual(telemetry.list_stop_updates(database=self.database), [event])

    def test_stop_event_scope_does_not_leak_other_clients(self):
        for client_id in (1, 2, None):
            self.ingest(self.snapshot(), client_id)
            updated = self.position()
            updated.update(sl=4060.22, sl_pnl=6)
            self.ingest(self.snapshot(LATER, [updated]), client_id)
        all_events = telemetry.list_stop_updates(database=self.database)
        self.assertEqual(len(all_events), 3)
        self.assertEqual(len({row["event_key"] for row in all_events}), 3)
        private = telemetry.list_stop_updates(1, database=self.database)
        self.assertEqual(len(private), 1)
        self.assertEqual(private[0]["client_id"], 1)

    def test_pending_recovery_filters_each_destination_outbox(self):
        for client_id in (1, 2, None):
            self.ingest(self.snapshot(), client_id)
            updated = self.position()
            updated.update(sl=4060.22, sl_pnl=6)
            self.ingest(self.snapshot(LATER, [updated]), client_id)
        events = {row['client_id']: row for row in telemetry.pending_stop_updates(database=self.database)}
        self.assertEqual(len(events), 3)
        with closing(sqlite3.connect(self.database)) as con, con:
            con.execute('CREATE TABLE owner_telegram_outbox(event_key TEXT PRIMARY KEY)')
            con.execute('CREATE TABLE azt_telegram_delivery(event_key TEXT UNIQUE)')
            con.execute('INSERT INTO owner_telegram_outbox VALUES(?)', (events[None]['event_key'],))
            con.execute('INSERT INTO azt_telegram_delivery VALUES(?)', (events[1]['event_key'],))
        pending = telemetry.pending_stop_updates(database=self.database)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['client_id'], 2)

    def test_filled_alias_and_changed_stop_do_not_reuse_execution_cash_estimate(self):
        telemetry.record_execution(None, KEY, '41', {'strategy_id': 'PULLBACK', 'stop_loss': 4067.34},
            trade_details={'entry': 4062.22, 'entry_basis': 'FILLED', 'sl_pnl': -15.36},
            database=self.database)
        row = self.position()
        row.update(sl=4060.22, sl_pnl=None, entry=None)
        self.ingest(self.snapshot(positions=[row]))
        stored, = telemetry.list_trades(database=self.database)
        self.assertEqual(stored['entry_basis'], 'ACTUAL_FILL')
        self.assertEqual(stored['sl'], 4060.22)
        self.assertIsNone(stored['sl_pnl'])

    def test_calibrated_history_ranges_include_new_deals_on_shifted_broker(self):
        now = datetime.now(timezone.utc)
        shift = 10800
        entry = NS(ticket=501, position_id=700, symbol="XAUUSD.c", type=0, entry=0,
                   volume=.03, price=4040., profit=0., commission=-.05, swap=0., fee=0.,
                   time=now.timestamp() + shift - 1800, comment="AZT:MARKET_STRUCTURE")
        exit_deal = NS(ticket=502, position_id=700, symbol="XAUUSD.c", type=1, entry=1,
                       volume=.03, price=4050., profit=30., commission=-.05, swap=0., fee=0.,
                       time=now.timestamp() + shift - 60, reason=5, comment="")
        api = self.api()
        api.positions_get.return_value = []
        api.DEAL_TYPE_BUY, api.DEAL_TYPE_SELL = 0, 1
        api.DEAL_ENTRY_IN, api.DEAL_ENTRY_OUT = 0, 1
        api.DEAL_ENTRY_INOUT, api.DEAL_ENTRY_OUT_BY = 2, 3
        api.DEAL_REASON_SL, api.DEAL_REASON_TP, api.DEAL_REASON_SO = 4, 5, 6
        api.history_deals_get.side_effect = (
            lambda start, end: [d for d in (entry, exit_deal) if start.timestamp() <= d.time <= end.timestamp()]
        )
        result = telemetry.capture_mt5(api, clock_offset_seconds=shift)
        self.assertEqual(result["history_sync"], "OK")
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"][0]["position_id"], "700")
        self.assertEqual(result["trades"][0]["strategy"], "MARKET_STRUCTURE")
        close_utc = datetime.fromisoformat(result["trades"][0]["closed_utc"])
        self.assertLess(abs((close_utc - (now - __import__("datetime").timedelta(seconds=60))).total_seconds()), 5)
        self.assertEqual(api.history_deals_get.call_count, 1)
        first_start, first_end = api.history_deals_get.call_args_list[0].args
        self.assertGreater(first_end, now + __import__("datetime").timedelta(hours=2))
        self.assertLess(first_start, now - __import__("datetime").timedelta(days=29))
        api.order_send.assert_not_called()

    def test_recent_history_fallback_when_wide_query_fails(self):
        api = self.api()
        api.history_deals_get.side_effect = [None, []]
        snap = telemetry.capture_mt5(api, clock_offset_seconds=0)
        self.assertEqual(snap["history_sync"], "DEGRADED")
        self.assertEqual(snap["history_window_failures"], 1)
        self.assertEqual(len(snap["positions"]), 1)
        api.order_send.assert_not_called()

    def test_history_unavailable_updates_open_positions_without_deleting_closed(self):
        closed = dict(ticket="888", position_id="888", symbol="XAUUSD.c", direction="SELL",
                      volume=.03, entry=4060., exit=4040., pnl=2., closed_utc=BASE)
        first = self.snapshot(positions=[self.position()], trades=[closed])
        first["history_sync"] = "OK"
        self.ingest(first)
        failed = self.snapshot(observed=LATER, positions=[], trades=[])
        failed.update(history_sync="UNAVAILABLE", history_window_failures=2)
        result = self.ingest(failed)
        self.assertTrue(result["accepted"])
        self.assertFalse(telemetry.list_trades(state="OPEN", database=self.database))
        saved_closed = telemetry.list_trades(state="CLOSED", database=self.database)
        self.assertEqual(len(saved_closed), 1)
        self.assertEqual(saved_closed[0]["ticket"], "888")
        a = telemetry.overview(database=self.database)["accounts"][0]
        self.assertEqual(a["history_sync"], "UNAVAILABLE")
        self.assertEqual(a["history_last_success_utc"], BASE)
        self.assertEqual(a["history_last_full_utc"], BASE)

    def test_partial_history_cannot_overwrite_confirmed_close(self):
        close = dict(ticket="888", position_id="888", symbol="XAUUSD.c",
                     direction="SELL", pnl=2.00, closed_utc=BASE)
        self.ingest(dict(self.snapshot(trades=[close]), history_sync="OK"))
        partial = dict(self.snapshot(observed=LATER, trades=[dict(close, pnl=2.50)]),
                       history_sync="DEGRADED", history_window_failures=1)
        self.ingest(partial)
        stored, = telemetry.list_trades(state="CLOSED", database=self.database)
        self.assertEqual(stored["pnl"], 2.00)

    def test_recent_only_close_alert_waits_for_full_history(self):
        self.ingest(dict(self.snapshot(), history_sync="OK"))
        close = dict(ticket="889", position_id="889", symbol="XAUUSD.c",
                     direction="SELL", pnl=2.50, closed_utc=LATER)
        partial = dict(self.snapshot(observed=LATER, trades=[close]),
                       history_sync="DEGRADED", history_window_failures=1)
        self.assertEqual(self.ingest(partial)["new_closed"], [])
        stored, = telemetry.list_trades(state="CLOSED", database=self.database)
        self.assertTrue(stored["history_partial"])
        complete = dict(self.snapshot(observed="2026-10-28T00:02:00+00:00",
                                      trades=[dict(close, pnl=2.00)]), history_sync="OK")
        reconciled, = self.ingest(complete)["new_closed"]
        self.assertEqual(reconciled["pnl"], 2.00)
        complete["observed_utc"] = "2026-10-28T00:03:00+00:00"
        self.assertEqual(self.ingest(complete)["new_closed"], [])


if __name__ == "__main__":
    unittest.main()
