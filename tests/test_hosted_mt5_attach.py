import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from server import hosted_worker as worker
from server.reconnect import SafetyStop, TemporaryConnectionError


class HostedAttachTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "terminal64.exe"
        self.path.touch()
        self.record = dict(terminal_path=str(self.path), mt5_login=123,
                           mt5_server="TestBroker", password_ciphertext="fixture")
        self.api = Mock()
        self.api.initialize.return_value = True
        self.api.account_info.return_value = SimpleNamespace(
            login=123, server="TestBroker", trade_allowed=True, trade_expert=True)
        self.api.terminal_info.return_value = SimpleNamespace(
            connected=True, trade_allowed=True, tradeapi_disabled=False,
            path=str(self.path.parent), data_path=str(self.path.parent))
        for name, value in (("mt5", self.api), ("set_hosted_account_status", Mock()),
                            ("set_hosted_runtime", Mock()),
                            ("hosted_account_for_client", Mock(return_value=self.record))):
            self.enterContext(patch.object(worker, name, value))

    def test_wrong_account_is_rejected_before_any_login(self):
        self.api.account_info.return_value.login = 456
        with self.assertRaises(SafetyStop):
            worker.connect_mt5(2)
        self.api.login.assert_not_called()

    def test_attach_accepts_ascii_case_variant_of_same_server(self):
        account = self.api.account_info.return_value
        account.server = "Testbroker"
        _, attached = worker.connect_mt5(2)
        self.assertIs(attached, account)
        self.api.login.assert_not_called()
        with self.assertRaisesRegex(SafetyStop, "account changed"):
            worker.verify_hosted_account(self.record)

    def test_attach_rejects_a_different_broker_server(self):
        for server in ("TestBroker-Live", "TestBro\u212aer"):
            with self.subTest(server=server):
                self.api.account_info.return_value.server = server
                with self.assertRaisesRegex(SafetyStop, "account changed"):
                    worker.connect_mt5(2)
        self.api.login.assert_not_called()

    def test_missing_account_does_not_initiate_broker_login(self):
        self.api.account_info.return_value = None
        with self.assertRaises(TemporaryConnectionError):
            worker.connect_mt5(2)
        self.api.login.assert_not_called()

    def test_portable_attach_uses_exact_path(self):
        worker.connect_mt5(2)
        self.api.initialize.assert_called_once_with(str(self.path.resolve()), timeout=10000, portable=True)
        self.api.login.assert_not_called()

    def test_nonportable_data_directory_or_wrong_installation_fails_closed(self):
        info = self.api.terminal_info.return_value
        for field in ("path", "data_path"):
            with self.subTest(field=field), patch.object(info, field, str(self.path.parent.parent)):
                with self.assertRaisesRegex(SafetyStop, field):
                    worker.connect_mt5(2)
        self.api.login.assert_not_called()

    def test_bad_path_is_rejected_before_initialization(self):
        self.record["terminal_path"] = str(self.path.with_name("missing.exe"))
        with self.assertRaises(SafetyStop):
            worker.connect_mt5(2)
        self.api.initialize.assert_not_called()

    def test_disconnect_during_attach_remains_retryable(self):
        self.api.terminal_info.return_value.connected = False
        with self.assertRaises(TemporaryConnectionError):
            worker.connect_mt5(2)
        self.api.login.assert_not_called()

    def test_permission_failures_are_distinct(self):
        for obj, field, value, message in (
            (self.api.terminal_info.return_value, "tradeapi_disabled", True, "Python API"),
            (self.api.terminal_info.return_value, "trade_allowed", False, "Algo Trading"),
            (self.api.account_info.return_value, "trade_expert", False, "Hosted account"),
        ):
            with self.subTest(field=field), patch.object(obj, field, value):
                with self.assertRaisesRegex(SafetyStop, message):
                    worker.connect_mt5(2)

    def test_duplicate_worker_cannot_attach_or_shutdown(self):
        with patch.object(worker, "client_by_id", return_value=SimpleNamespace(status="ACTIVE", execution_mode="HOSTED")), \
             patch.object(worker, "subscription_access", return_value={"allowed": True}), \
             patch.object(worker, "_acquire_account_lock", side_effect=SafetyStop("already controls")), \
             self.assertRaisesRegex(SafetyStop, "already controls"):
            worker.run(2)
        self.api.initialize.assert_not_called()
        self.api.shutdown.assert_not_called()
        worker.set_hosted_runtime.assert_not_called()
        worker.set_hosted_account_status.assert_not_called()

    def test_busy_reported_server_lock_blocks_hosted_processing(self):
        self.api.account_info.return_value.server = "Testbroker"
        configured_lock = Mock()
        client = SimpleNamespace(status="ACTIVE", execution_mode="HOSTED")
        with (
            patch.object(worker, "client_by_id", return_value=client),
            patch.object(worker, "subscription_access", return_value={"allowed": True}),
            patch.object(worker, "_acquire_account_lock",
                         side_effect=[configured_lock, SafetyStop("already controls")]) as acquire,
            patch.object(worker, "next_instruction") as next_instruction,
            self.assertRaisesRegex(SafetyStop, "already controls"),
        ):
            worker.run(2)
        self.assertEqual(acquire.call_args_list, [
            call(self.record),
            call({**self.record, "mt5_server": "Testbroker"}),
        ])
        self.assertNotIn(call(2, "ACTIVE"), worker.set_hosted_account_status.call_args_list)
        next_instruction.assert_not_called()
        self.api.order_send.assert_not_called()
        self.api.shutdown.assert_called_once()
        configured_lock.close.assert_called_once()

    def test_case_variant_holds_both_locks_until_hosted_shutdown(self):
        account = self.api.account_info.return_value
        account.server = "Testbroker"
        account.balance = account.equity = 1000
        configured_lock, reported_lock = Mock(), Mock()
        client = SimpleNamespace(status="ACTIVE", execution_mode="HOSTED")
        stop = threading.Event()

        def finish(_client_id):
            configured_lock.close.assert_not_called()
            reported_lock.close.assert_not_called()
            stop.set()
            return None

        with (
            patch.object(worker, "client_by_id", return_value=client),
            patch.object(worker, "subscription_access", return_value={"allowed": True}),
            patch.object(worker, "_acquire_account_lock",
                         side_effect=[configured_lock, reported_lock]) as acquire,
            patch.object(worker, "_capture_hosted"),
            patch.object(worker, "next_instruction", side_effect=finish) as next_instruction,
        ):
            worker.run(2, stop)
        self.assertEqual(acquire.call_args_list, [
            call(self.record),
            call({**self.record, "mt5_server": "Testbroker"}),
        ])
        next_instruction.assert_called_once_with(2)
        self.api.shutdown.assert_called_once()
        configured_lock.close.assert_called_once()
        reported_lock.close.assert_called_once()
        self.api.order_send.assert_not_called()

    def test_temporary_ipc_failure_retries_with_one_lock_then_shuts_down(self):
        stop = threading.Event()
        lock = Mock()
        self.api.initialize.side_effect = [False, True]
        def finish(_client_id):
            stop.set()
            return None
        with patch.object(worker, "client_by_id", return_value=SimpleNamespace(status="ACTIVE", execution_mode="HOSTED")), \
             patch.object(worker, "subscription_access", return_value={"allowed": True}), \
             patch.object(worker, "_acquire_account_lock", return_value=lock) as acquire, \
             patch.object(worker, "_capture_hosted"), patch.object(worker, "_notify"), \
             patch.object(worker, "next_instruction", side_effect=finish), patch.object(stop, "wait") as wait:
            self.api.account_info.return_value.balance = 1000
            self.api.account_info.return_value.equity = 1000
            worker.run(2, stop)
        acquire.assert_called_once_with(self.record)
        self.assertEqual(self.api.initialize.call_count, 2)
        self.assertEqual(self.api.shutdown.call_count, 2)
        self.assertGreater(wait.call_args_list[0].args[0], 0)
        lock.close.assert_called_once()
        self.api.login.assert_not_called()
        self.api.order_send.assert_not_called()
