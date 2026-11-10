import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from broker.symbols import resolve_symbol
from server import personal_worker as personal
from server import hosted_worker as hosted
from server import hosted_executor
from server import trade_telemetry as telemetry
from server.reconnect import RetryPolicy, RetryState, TemporaryConnectionError, SafetyStop


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


class SymbolResolutionTests(unittest.TestCase):
    def api(self, names):
        api = Mock()
        api.symbols_get.return_value = [NS(name=name) for name in names]
        api.symbol_info.side_effect = lambda name: NS(visible=True, volume_min=.01, volume_max=100,
            volume_step=.01, trade_contract_size=100, point=.01, currency_base="XAU",
            currency_profit="USD", trade_mode=4, path="Metals\\Gold")
        return api

    def test_owner_suffix_is_not_copied_to_clients(self):
        for local in ("XAUUSD.m", "XAUUSD.a", "XAUUSD", "GOLD", "pro.XAUUSD.c", "GOLDmicro"):
            with self.subTest(local=local):
                api = self.api(["XAUEUR", "SILVER", local])
                self.assertEqual(resolve_symbol(api, "XAUUSD.c"), local)
                api.order_send.assert_not_called()

    def test_invalid_or_disabled_contracts_are_not_selected(self):
        api = self.api(["XAUUSD", "XAUUSD.m"])
        valid = api.symbol_info("XAUUSD.m")
        for bad in (NS(**{**vars(valid), "trade_mode": 0}), NS(**{**vars(valid), "currency_profit": "EUR"}),
                    NS(**{**vars(valid), "volume_step": 0}), NS(**{**vars(valid), "path": "Futures\\Gold"})):
            with self.subTest(bad=bad):
                api.symbol_info.side_effect = lambda name: bad if name == "XAUUSD" else valid
                self.assertEqual(resolve_symbol(api, "GOLD"), "XAUUSD.m")

    def test_other_metals_and_non_usd_gold_are_rejected(self):
        for symbol in ("XAUEUR", "GOLDINDEX", "GOLDEUR", "XAGUSD"):
            with self.subTest(symbol=symbol), self.assertRaisesRegex(RuntimeError, "No valid"):
                resolve_symbol(self.api([symbol]), "GOLD")

    def test_unselectable_invisible_contract_is_not_used(self):
        api = self.api(["GOLD"])
        info = api.symbol_info("GOLD")
        info.visible = False
        api.symbol_info.side_effect = lambda _: info
        api.symbol_select.return_value = False
        with self.assertRaises(RuntimeError):
            resolve_symbol(api, "GOLD")


class ReconnectTests(unittest.TestCase):
    def test_position_query_failure_is_not_zero_open_risk(self):
        api = Mock()
        api.account_info.return_value = NS(equity=1000)
        with patch.object(hosted_executor, "mt5", api):
            api.positions_get.return_value = None
            self.assertEqual(hosted_executor._open_risk_pct(True), float("inf"))
            api.positions_get.return_value = []
            self.assertEqual(hosted_executor._open_risk_pct(True), 0)
        api.order_send.assert_not_called()

    def test_nonfinite_position_risk_cannot_bypass_portfolio_ceiling(self):
        api = Mock()
        api.POSITION_TYPE_BUY = 0
        api.account_info.return_value = NS(equity=1000)
        api.positions_get.return_value = [NS(type=0, symbol="GOLD", volume=.01, price_open=2000, sl=1990)]
        with patch.object(hosted_executor, "mt5", api):
            api.order_calc_profit.return_value = float("nan")
            self.assertEqual(hosted_executor._open_risk_pct(True), float("inf"))
            with self.assertRaisesRegex(RuntimeError, "non-finite"):
                hosted_executor._loss("BUY", "GOLD", .01, 2000, 1990)
        api.order_send.assert_not_called()

    def test_backoff_threshold_cooldown_and_recovery(self):
        retry = RetryState(RetryPolicy(5, 30, 3, 100))
        self.assertEqual([retry.failed() for _ in range(5)], [5, 10, 20, 30, 30])
        self.assertEqual(retry.state, "DEGRADED")
        self.assertTrue(retry.should_alert(now=0))
        self.assertFalse(retry.should_alert(now=99))
        self.assertTrue(retry.should_alert(now=100))
        self.assertTrue(retry.recovered())
        self.assertEqual(retry.failures, 0)
        self.assertEqual(retry.failed(), 5)

    def test_policy_reads_shared_workspace_settings_and_bounds_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "workspace_settings.json").write_text(json.dumps({"retry_interval": 7,
                "retry_cap": 40, "retries_before_alert": 4, "alert_cooldown": 80}))
            with patch.dict(os.environ, {"GOLD_AI_STATE_DIR": directory}):
                self.assertEqual(RetryPolicy.load(), RetryPolicy(7, 40, 4, 80))

    def test_personal_desired_state_survives_outage_and_reconnect_discards_backlog(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = Path(directory, "terminal64.exe")
            terminal.touch()
            settings = {"terminal_path": str(terminal), "login": 123, "server": "Broker"}
            account = NS(login=123, server="Broker", equity=1000)
            stop = threading.Event()
            queries, statuses = [], []
            def signal(cursor, since):
                queries.append((cursor, since))
                return None
            def wait(delay):
                if delay == 1 and len(queries) == 2:
                    stop.set()
            fake_time = NS(time=Mock(side_effect=[100, 101, 200]), monotonic=lambda: 0)
            retry = RetryState(RetryPolicy())
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}), patch.object(personal, "load_settings", return_value=settings), \
                 patch.object(personal, "attach") as attach, patch.object(personal, "verify_account", side_effect=[account, account,
                 TemporaryConnectionError("offline"), account, account]), patch.object(personal, "mt5") as mt5, \
                 patch.object(personal, "time", fake_time), patch.object(personal, "RetryState", return_value=retry), \
                 patch.object(personal, "next_signal", side_effect=signal), patch.object(personal, "_capture_telemetry"), \
                 patch.object(personal, "_runtime_alert") as alert, patch.object(personal, "write_status", side_effect=lambda _, **state: statuses.append(state)), \
                 patch.object(stop, "wait", side_effect=wait):
                personal.run(stop)
            self.assertEqual(attach.call_count, 2)
            self.assertEqual(queries, [(0, 101), (0, 200)])
            reconnect = next(state for state in statuses if state["state"] == "RECONNECTING")
            self.assertTrue(reconnect["desired"])
            self.assertEqual(reconnect["retry_in"], 5)
            self.assertIn("RECOVERED", [call.args[1] for call in alert.call_args_list])
            self.assertEqual(mt5.shutdown.call_count, 2)
            mt5.order_send.assert_not_called()

    def test_personal_account_mismatch_is_a_safety_stop_not_auto_login(self):
        api = Mock()
        api.account_info.return_value = NS(login=999, server="Broker")
        api.terminal_info.return_value = NS(connected=True)
        with patch.object(personal, "mt5", api), self.assertRaises(SafetyStop):
            personal.verify_account({"login": 123, "server": "Broker"})
        api.login.assert_not_called()

    def test_personal_cannot_duplicate_a_clients_secondary_mt5_account(self):
        api = Mock()
        api.account_info.return_value = NS(login=123, server="Broker", equity=1000, trade_allowed=True, trade_expert=True)
        api.terminal_info.return_value = NS(connected=True, trade_allowed=True, tradeapi_disabled=False)
        client = NS(id=1, name="Client", mt5_login=999, mt5_server="Broker", status="ACTIVE")
        with patch.object(personal, "mt5", api), patch.object(personal, "list_clients", return_value=[client]), \
             patch("server.azt_store.list_accounts", return_value=[{"login": 123, "server": "Broker", "status": "ACTIVE"}]), \
             self.assertRaisesRegex(SafetyStop, "duplicate orders"):
            personal.verify_account({"login": 123, "server": "Broker"})
        api.order_send.assert_not_called()

    def test_paused_clients_do_not_block_independent_personal_execution(self):
        api = Mock()
        api.account_info.return_value = NS(login=123, server="Broker", equity=1000, trade_allowed=True, trade_expert=True)
        api.terminal_info.return_value = NS(connected=True, trade_allowed=True, tradeapi_disabled=False)
        for primary_login in (123, 999):
            with self.subTest(primary_login=primary_login):
                client = NS(id=1, name="Paused Client", mt5_login=primary_login, mt5_server="Broker", status="PAUSED")
                with patch.object(personal, "mt5", api), patch.object(personal, "list_clients", return_value=[client]), \
                     patch.object(personal, "list_hosted_accounts", return_value=[]), \
                     patch("server.azt_store.list_accounts", return_value=[{"login": 123, "server": "Broker", "status": "ACTIVE"}]) as registry:
                    result = personal.verify_account({"login": 123, "server": "Broker"})
                self.assertEqual(result.login, 123)
                registry.assert_not_called()
        api.order_send.assert_not_called()

    def test_disabled_secondary_binding_does_not_block_personal_execution(self):
        api = Mock()
        api.account_info.return_value = NS(login=123, server="Broker", equity=1000, trade_allowed=True, trade_expert=True)
        api.terminal_info.return_value = NS(connected=True, trade_allowed=True, tradeapi_disabled=False)
        client = NS(id=1, name="Client", mt5_login=999, mt5_server="Broker", status="ACTIVE")
        with patch.object(personal, "mt5", api), patch.object(personal, "list_clients", return_value=[client]), \
             patch.object(personal, "list_hosted_accounts", return_value=[]), \
             patch("server.azt_store.list_accounts", return_value=[{"login": 123, "server": "Broker", "status": "DISABLED"}]):
            self.assertEqual(personal.verify_account({"login": 123, "server": "Broker"}).login, 123)
        api.order_send.assert_not_called()

    def test_final_personal_guard_rechecks_stop_identity_and_policy_after_slow_db_gate(self):
        settings = {"login": 123, "server": "Broker", "risk_per_trade_pct": .9, "max_open_risk_pct": 40, "max_daily_loss_pct": 5}
        policy = {"risk_per_trade_pct": .9, "max_open_risk_pct": 40, "max_daily_loss_pct": 5,
                  "daily_profit_target_enabled": False, "daily_profit_target_pct": 0}
        for change, expected in (("stop", "stopped"), ("account", "account changed"), ("policy", "Risk policy changed")):
            with self.subTest(change=change):
                stop, send = threading.Event(), Mock()
                account = NS(login=123, server="Broker", equity=1000, trade_allowed=True, trade_expert=True)
                api = Mock()
                api.account_info.return_value = account
                api.terminal_info.return_value = NS(connected=True, trade_allowed=True, tradeapi_disabled=False)
                calls = [0]
                def latest(_):
                    calls[0] += 1
                    if calls[0] > 1:
                        if change == "stop": stop.set()
                        if change == "account": account.login = 999
                        if change == "policy": return {**policy, "risk_per_trade_pct": .5}
                    return policy
                def execute(*_args, **kwargs):
                    kwargs["before_send"]()
                    send()
                row = {"payload": json.dumps({"setup_time": datetime.now(timezone.utc).isoformat()})}
                with patch.object(personal, "mt5", api), patch.object(personal, "list_clients", return_value=[]), \
                     patch.object(personal, "list_hosted_accounts", return_value=[]), patch.object(personal, "news_lock_enabled", return_value=False), \
                     patch.object(personal, "effective_risk_policy", side_effect=latest), patch.object(personal, "execute_instruction", side_effect=execute), \
                     self.assertRaisesRegex(RuntimeError, expected):
                    personal.execute_signal(row, settings, stop)
                send.assert_not_called()

    def test_hosted_guard_checks_server_as_well_as_login(self):
        api = Mock()
        api.account_info.return_value = NS(login=123, server="Other")
        api.terminal_info.return_value = NS(connected=True)
        with patch.object(hosted, "mt5", api), self.assertRaises(SafetyStop):
            hosted.verify_hosted_account({"mt5_login": 123, "mt5_server": "Broker"})
        api.order_send.assert_not_called()

    def test_hosted_age_limits_reject_stale_future_or_naive_timestamps(self):
        for seconds, expected in ((-1200, True), (60, True), (-1201, False), (61, False)):
            with self.subTest(seconds=seconds):
                self.assertEqual(hosted.signal_is_fresh({"setup_time": (NOW + timedelta(seconds=seconds)).isoformat()}, now=NOW), expected)
        self.assertFalse(hosted.signal_is_fresh({"setup_time": "2026-10-27T12:00:00"}, now=NOW))

    def test_hosted_queued_signal_before_start_never_submits(self):
        stop = threading.Event()
        account = NS(login=123, server="Broker", equity=1000, balance=1000)
        row = {"id": 1, "signal_key": "old", "created_utc": (NOW-timedelta(seconds=1)).isoformat(),
               "payload_json": json.dumps({"setup_time": NOW.isoformat(), "direction": "BUY"})}
        clock = Mock()
        clock.now.return_value = NOW
        clock.fromisoformat.side_effect = datetime.fromisoformat
        with patch.object(hosted, "datetime", clock), patch.object(hosted, "client_by_id", return_value=NS(status="ACTIVE", execution_mode="HOSTED")), \
             patch.object(hosted, "subscription_access", return_value={"allowed": True}), \
             patch.object(hosted, "hosted_account_for_client", return_value={"mt5_login": 123, "mt5_server": "Broker", "terminal_path": "fixture"}), \
             patch.object(hosted, "connect_mt5", return_value=({"mt5_login": 123, "mt5_server": "Broker"}, account)), \
             patch.object(hosted, "verify_hosted_account", return_value=account), patch.object(hosted, "_capture_hosted"), \
             patch.object(hosted, "_acquire_account_lock"), \
             patch.object(hosted, "set_hosted_account_status"), patch.object(hosted, "set_hosted_runtime"), \
             patch.object(hosted, "next_instruction", side_effect=[row, None]), patch.object(hosted, "acknowledge_instruction") as ack, \
             patch.object(hosted, "claim_signal") as claim, patch.object(hosted, "execute_instruction") as execute, \
             patch.object(hosted, "mt5") as mt5, patch.object(stop, "wait", side_effect=lambda _: stop.set()):
            hosted.run(1, stop)
        self.assertEqual(ack.call_args.args[2], "SKIPPED")
        claim.assert_not_called()
        execute.assert_not_called()
        mt5.order_send.assert_not_called()

    def test_signal_engine_reconnects_without_publishing_owner_symbol_suffix(self):
        from dataclasses import make_dataclass
        from server import signal_engine as engine
        signal_type = make_dataclass("Signal", ["strategy_id", "direction", "setup_time", "stop_loss", "take_profit"])
        signal = signal_type("TEST", "BUY", datetime.now(timezone.utc).isoformat(), 1990, 2020)
        stop = threading.Event()
        client = Mock(symbol="XAUUSD.c", clock=NS(offset_seconds=0))
        client.candles.side_effect = [RuntimeError("network interrupted"), []]
        registry = Mock()
        registry.scan.return_value = [signal]
        waits = []
        def wait(delay):
            waits.append(delay)
            if len(waits) >= 2:
                stop.set()
        with patch.object(engine, "ACTIVE_MARKETS", {"GOLD": "XAUUSD.c"}), patch.object(engine, "MT5Client", return_value=client), \
             patch.object(engine, "StrategyRegistry", return_value=registry), patch.object(engine, "active_clients", return_value=[]), \
             patch.object(engine, "news_lock_enabled", return_value=False), patch.object(engine, "write_status"), \
             patch.object(engine, "RetryState", return_value=RetryState(RetryPolicy())), patch.object(engine, "publish_signal") as publish, \
             patch.object(stop, "wait", side_effect=wait):
            engine.main(stop)
        self.assertEqual(client.connect.call_count, 2)
        self.assertEqual(waits[0], 5)
        self.assertEqual(publish.call_args.args[1]["symbol_hint"], "GOLD")


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name, "test.db")

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, observed, *, positions=None, trades=None, currency="USD"):
        return {"observed_utc": observed, "account": {"login": 123, "server": "Broker", "currency": currency,
                "balance": 1000, "equity": 1001, "password": "DO_NOT_STORE"}, "positions": positions or [], "trades": trades or []}

    def row(self, ticket="1", **overrides):
        return {"ticket": ticket, "symbol": "XAUUSD.m", "direction": "BUY", "volume": .01,
                "entry": 2000, "pnl": 5, "opened_utc": "2026-10-27T11:00:00+00:00",
                "closed_utc": "2026-10-27T12:00:00+00:00", **overrides}

    def ingest(self, snapshot, client_id=1, key="Broker|123"):
        return telemetry.ingest_snapshot(client_id, key, snapshot, database=self.database)

    def test_history_sync_is_silent_and_new_events_deduplicate_with_real_currency(self):
        result = self.ingest(self.snapshot("2026-10-27T12:00:00+00:00", trades=[self.row()]))
        self.assertEqual((result["new_open"], result["new_closed"]), ([], []))
        position = self.row("2", opened_utc="2026-10-27T12:00:30+00:00", sl=1990, tp=2020, strategy="PULLBACK")
        result = self.ingest(self.snapshot("2026-10-27T12:01:00+00:00", positions=[position]))
        self.assertEqual(result["new_open"][0]["currency"], "USD")
        self.assertEqual(result["new_open"][0]["account_key"], "Broker|123")
        closed = self.row("2", opened_utc=None, closed_utc="2026-10-27T12:01:30+00:00", entry=None, close_reason="SL HIT", pnl=3)
        result = self.ingest(self.snapshot("2026-10-27T12:02:00+00:00", trades=[closed]))
        self.assertEqual(len(result["new_closed"]), 1)
        actual = result["new_closed"][0]
        self.assertEqual((actual["sl"], actual["strategy"], actual["entry"]), (1990, "PULLBACK", 2000))
        self.assertEqual(actual["result"], "SL HIT")  # A trailing SL can close in profit.
        self.assertEqual(self.ingest(self.snapshot("2026-10-27T12:03:00+00:00", trades=[closed]))["new_closed"], [])
        self.assertNotIn(b"DO_NOT_STORE", self.database.read_bytes())

    def test_timezone_journal_boundary_uses_true_utc(self):
        row = self.row(closed_utc="2026-10-27T01:30:00+03:00")
        self.ingest(self.snapshot("2026-10-27T12:00:00+00:00", trades=[row]))
        rows = telemetry.list_trades(1, database=self.database)
        self.assertEqual(rows[0]["closed_utc"], "2026-10-26T22:30:00+00:00")
        utc = telemetry.daily_journal(1, "2026-10-27", "UTC", database=self.database)
        eat = telemetry.daily_journal(1, "2026-10-27", "Africa/Kampala", database=self.database)
        self.assertEqual((utc["trades_taken"], eat["trades_taken"]), (0, 1))
        self.assertEqual(eat["pnl"], 5)
        self.assertIsNone(eat["risk_used"])

    def test_client_scope_and_mixed_currency_totals(self):
        self.ingest(self.snapshot(NOW.isoformat(), trades=[self.row()]))
        second = self.snapshot(NOW.isoformat(), trades=[self.row("2", pnl=-2)], currency="EUR")
        second["account"].update(login=456, server="Other")
        self.ingest(second, client_id=2, key="Other|456")
        self.assertEqual(len(telemetry.list_trades(1, database=self.database)), 1)
        with patch.object(telemetry, "datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            aggregate = telemetry.overview(timezone="UTC", database=self.database)
            clock.now.return_value = NOW + timedelta(days=1)
            tomorrow = telemetry.overview(timezone="UTC", database=self.database)
        self.assertIsNone(aggregate["today_pnl"])
        self.assertEqual(aggregate["today_pnl_by_currency"], {"USD": 5, "EUR": -2})
        self.assertEqual(tomorrow["today_pnl"], 0)
        self.assertEqual(tomorrow["today_pnl_by_currency"], {})

    def test_invalid_snapshot_does_not_destroy_last_complete_snapshot(self):
        self.ingest(self.snapshot(NOW.isoformat(), positions=[self.row()]))
        with self.assertRaises(ValueError):
            self.ingest(self.snapshot(NOW.isoformat(), positions=[self.row(pnl=float("nan"))]))
        self.assertEqual(len(telemetry.list_trades(1, state="OPEN", database=self.database)), 1)
        with self.assertRaisesRegex(ValueError, "explicit UTC offset"):
            telemetry.utc_iso("2026-10-27T12:00:00")

    def test_stale_snapshot_cannot_reopen_old_positions(self):
        self.ingest(self.snapshot("2026-10-27T12:00:00+00:00"))
        result = self.ingest(self.snapshot("2026-10-27T11:00:00+00:00", positions=[self.row()]))
        self.assertFalse(result["accepted"])
        self.assertEqual(telemetry.list_trades(1, database=self.database), [])

    def test_snapshot_cannot_be_written_under_another_mt5_account(self):
        with self.assertRaisesRegex(ValueError, "scoped MT5 account"):
            self.ingest(self.snapshot(NOW.isoformat()), key="AnotherBroker|999")
        self.assertFalse(self.database.exists())

    def test_known_execution_risk_is_preserved_without_fabricating_unknowns(self):
        telemetry.record_execution(1, "Broker|123", "1", {"strategy_id": "PULLBACK", "stop_loss": 1990, "take_profit": 2020}, risk_pct=.9, database=self.database)
        self.ingest(self.snapshot(NOW.isoformat(), trades=[self.row()]))
        journal = telemetry.daily_journal(1, "2026-10-27", database=self.database)
        self.assertEqual(journal["risk_used"], .9)
        self.assertEqual(journal["strategies_used"], ["PULLBACK"])

    def test_mt5_capture_normalizes_broker_history_and_counts_net_costs(self):
        api = Mock()
        for key, value in {"DEAL_TYPE_BUY": 0, "DEAL_TYPE_SELL": 1, "DEAL_ENTRY_IN": 0, "DEAL_ENTRY_OUT": 1,
                           "DEAL_ENTRY_INOUT": 2, "DEAL_ENTRY_OUT_BY": 3, "DEAL_REASON_SL": 4, "DEAL_REASON_TP": 5, "DEAL_REASON_SO": 6}.items():
            setattr(api, key, value)
        api.account_info.return_value = NS(login=123, server="Broker", currency="USD", balance=1000, equity=1000)
        api.terminal_info.return_value = NS(connected=True)
        api.positions_get.return_value = []
        raw = NOW.timestamp() + 7200
        entry = NS(position_id=7, type=0, entry=0, time=raw-300, volume=.01, price=2000, symbol="XAUUSD.m", profit=0, commission=-.2, comment="AZT:PULLBACK")
        close = NS(position_id=7, type=1, entry=1, time=raw, volume=.01, price=2005, symbol="XAUUSD.m", profit=5, commission=-.1, reason=4)
        api.history_deals_get.return_value = [entry, close]
        snapshot = telemetry.capture_mt5(api, clock_offset_seconds=7200)
        trade = snapshot["trades"][0]
        self.assertEqual(trade["closed_utc"], NOW.isoformat())
        self.assertAlmostEqual(trade["pnl"], 4.7)
        self.assertEqual(trade["close_reason"], "SL HIT")
        self.assertEqual(trade["strategy"], "PULLBACK")
        api.order_send.assert_not_called()

    def test_missing_mt5_positions_does_not_create_false_closure_snapshot(self):
        api = Mock()
        api.account_info.return_value = NS(login=123)
        api.terminal_info.return_value = NS(connected=True)
        api.positions_get.return_value = None
        api.history_deals_get.return_value = []
        with self.assertRaisesRegex(RuntimeError, "last snapshot retained"):
            telemetry.capture_mt5(api)

    def test_partial_exits_contribute_actual_pnl_without_duplicate_trade_or_risk_count(self):
        first = self.row("exit-1", position_id="position-1", pnl=2, risk_pct=.9, is_partial_close=True)
        last = self.row("exit-2", position_id="position-1", pnl=3, risk_pct=.9)
        self.ingest(self.snapshot(NOW.isoformat(), trades=[first, last]))
        journal = telemetry.daily_journal(1, "2026-10-27", database=self.database)
        self.assertEqual((journal["trades_taken"], journal["closed_deals"]), (1, 2))
        self.assertEqual((journal["pnl"], journal["risk_used"], journal["wins"]), (5, .9, 1))

    def test_delayed_confirmed_deal_can_notify_after_a_later_empty_poll(self):
        self.ingest(self.snapshot("2026-10-27T12:00:00+00:00"))
        self.ingest(self.snapshot("2026-10-27T12:05:00+00:00"))
        delayed = self.row(closed_utc="2026-10-27T12:04:00+00:00")
        result = self.ingest(self.snapshot("2026-10-27T12:06:00+00:00", trades=[delayed]))
        self.assertEqual(len(result["new_closed"]), 1)

    def test_recent_trade_limit_uses_close_time_not_snapshot_poll_time(self):
        old = self.row("old", closed_utc="2026-10-26T12:00:00+00:00")
        new = self.row("new", closed_utc="2026-10-27T12:00:00+00:00")
        self.ingest(self.snapshot(NOW.isoformat(), trades=[old, new]))
        rows = telemetry.list_trades(1, limit=1, database=self.database)
        self.assertEqual(rows[0]["ticket"], "new")


if __name__ == "__main__":
    unittest.main()
