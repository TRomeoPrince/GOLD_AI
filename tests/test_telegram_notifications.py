import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from server import telegram_notifications as notifications
from server.client_telegram import TelegramRequestError


TOKEN_A = "123456:" + "A" * 35
TOKEN_B = "987654:" + "B" * 35
ENVIRONMENT = {
    "GOLD_AI_OWNER_TELEGRAM_ENABLED": "true",
    "GOLD_AI_OWNER_TELEGRAM_BOT_TOKEN": TOKEN_A,
    "TELEGRAM_BOT_TOKEN": "",
    "GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN": "",
    "GOLD_AI_OWNER_TELEGRAM_CHAT_ID": "111",
    "TELEGRAM_ADMIN_ID": "",
}


class OwnerNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "outbox.db"
        self.environment = patch.dict(os.environ, ENVIRONMENT)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def enqueue(self, key="event-1", text="Owner event"):
        return notifications.enqueue_owner_event(key, text, database=self.database)

    def rows(self):
        with notifications._connection(self.database) as con:
            return [dict(row) for row in con.execute("SELECT * FROM owner_telegram_outbox ORDER BY event_key")]

    def sender_until(self, predicate, *, bot=None):
        stop = threading.Event()
        statuses = []
        bot = bot if bot is not None else Mock()
        if not isinstance(bot.send_message.side_effect, BaseException) and bot.send_message.side_effect is None:
            bot.send_message.return_value = 42
        def status(_name, **values):
            statuses.append(values)
            if predicate(values) or len(statuses) >= 30:
                stop.set()
        with patch.object(notifications, "ClientTelegramBot", return_value=bot) as transport, patch.object(notifications, "write_status", side_effect=status):
            notifications.run(stop, database=self.database)
        return bot, transport, statuses

    def test_enqueue_is_network_free_deduplicated_and_never_stores_token(self):
        with patch.object(notifications, "ClientTelegramBot") as network:
            self.assertTrue(self.enqueue())
            self.assertFalse(self.enqueue(text="Changed body must not create a second alert"))
        network.assert_not_called()
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chat_id"], 111)
        self.assertEqual(rows[0]["token_fingerprint"], hashlib.sha256(TOKEN_A.encode()).hexdigest())
        self.assertEqual(rows[0]["message"], "Owner event")
        self.assertNotIn(TOKEN_A, str(rows))
        self.assertNotIn(TOKEN_A, repr(notifications._owner_config()))

    def test_configuration_priority_and_explicit_fallback(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN_B, "TELEGRAM_ADMIN_ID": "222"}):
            config = notifications._owner_config()
            self.assertEqual((config.token, config.chat_id), (TOKEN_A, 111))
            with patch.dict(os.environ, {"GOLD_AI_OWNER_TELEGRAM_BOT_TOKEN": "", "GOLD_AI_OWNER_TELEGRAM_CHAT_ID": ""}):
                config = notifications._owner_config()
                self.assertEqual((config.token, config.chat_id), (TOKEN_B, 222))
                with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN": TOKEN_A}):
                    self.assertEqual(notifications._owner_config().token, TOKEN_A)

    def test_invalid_or_disabled_configuration_does_not_guess_a_recipient(self):
        for changes in (
            {"GOLD_AI_OWNER_TELEGRAM_ENABLED": "false"},
            {"GOLD_AI_OWNER_TELEGRAM_CHAT_ID": "not-a-chat", "TELEGRAM_ADMIN_ID": "222"},
            {"GOLD_AI_OWNER_TELEGRAM_CHAT_ID": "0"},
            {"GOLD_AI_OWNER_TELEGRAM_CHAT_ID": "9" * 5000},
            {"GOLD_AI_OWNER_TELEGRAM_BOT_TOKEN": "YOUR_TOKEN", "TELEGRAM_BOT_TOKEN": TOKEN_B},
        ):
            with self.subTest(changes=tuple(changes)), patch.dict(os.environ, changes):
                self.assertFalse(self.enqueue())
        self.assertFalse(self.database.exists())

    def test_queue_io_failure_never_propagates_into_trading(self):
        with patch.object(notifications.sqlite3, "connect", side_effect=OSError("private data")), self.assertLogs(level="WARNING") as logs:
            self.assertFalse(self.enqueue())
        self.assertNotIn("private data", str(logs.output))

    def test_disabled_sender_exits_without_a_transport_call(self):
        with patch.dict(os.environ, {"GOLD_AI_OWNER_TELEGRAM_ENABLED": "false"}):
            _bot, transport, statuses = self.sender_until(lambda state: state["state"] == "NOT_CONFIGURED")
        transport.assert_not_called()
        self.assertEqual([state["state"] for state in statuses], ["NOT_CONFIGURED"])

    def test_success_is_marked_sent_and_not_resent_after_restart(self):
        self.enqueue()
        bot, transport, statuses = self.sender_until(lambda state: state["state"] == "DELIVERED")
        transport.assert_called_once_with(token=TOKEN_A)
        bot.send_message.assert_called_once_with(111, "Owner event")
        self.assertEqual(self.rows()[0]["state"], "SENT")
        self.assertEqual(self.rows()[0]["message_id"], 42)
        self.assertIn("SENDING", [state["state"] for state in statuses])
        _bot, transport, statuses = self.sender_until(lambda state: state["state"] == "IDLE")
        transport.assert_not_called()
        self.assertEqual(self.rows()[0]["attempts"], 1)
        self.assertIn("1 delivered", statuses[0]["message"])

    def test_waiting_retry_remains_visible_and_errors_are_sanitized(self):
        self.enqueue()
        bot = Mock()
        bot.send_message.side_effect = TelegramRequestError(f"Timeout {TOKEN_A} https://api.telegram.org/bot{TOKEN_A}/sendMessage")
        with self.assertLogs(level="WARNING") as logs:
            _bot, _transport, statuses = self.sender_until(lambda state: state["state"] == "RETRYING", bot=bot)
        row = self.rows()[0]
        self.assertEqual((row["state"], row["attempts"]), ("RETRY", 1))
        self.assertGreater(row["next_attempt"], row["updated"])
        retry = next(state for state in statuses if state["state"] == "RETRYING")
        self.assertEqual(retry["retrying"], 1)
        self.assertIn("Last issue:", retry["message"])
        self.assertNotIn(TOKEN_A, str(row) + str(statuses) + str(logs.output))
        self.assertNotIn("https://", str(statuses) + str(logs.output))
        bot.send_message.assert_called_once()

    def test_retry_attempts_stop_at_five_and_failed_state_stays_visible(self):
        self.enqueue()
        bot = Mock()
        bot.send_message.side_effect = TimeoutError("private data")
        clock = [time.time()]
        def progress(state):
            if state["state"] == "ERROR":
                clock[0] += 130
            return state["state"] == "ERROR" and bot.send_message.call_count >= 5
        with patch.object(notifications.time, "time", side_effect=lambda: clock[0]), patch.object(threading.Event, "wait", return_value=False), self.assertLogs(level="WARNING"):
            self.sender_until(progress, bot=bot)
        row = self.rows()[0]
        self.assertEqual((row["state"], row["attempts"]), ("FAILED", 5))
        self.assertEqual(bot.send_message.call_count, 5)
        _bot, transport, statuses = self.sender_until(lambda state: state["state"] == "FAILED")
        transport.assert_not_called()
        self.assertEqual(statuses[0]["failed"], 1)

    def test_configuration_changes_hold_rows_without_rerouting(self):
        self.enqueue()
        original = self.rows()[0]
        with patch.dict(os.environ, {"GOLD_AI_OWNER_TELEGRAM_BOT_TOKEN": TOKEN_B, "GOLD_AI_OWNER_TELEGRAM_CHAT_ID": "222"}):
            _bot, transport, statuses = self.sender_until(lambda state: state["state"] == "HELD")
            transport.assert_not_called()
            held = self.rows()[0]
            self.assertEqual(held["state"], "HELD")
            self.assertEqual((held["chat_id"], held["token_fingerprint"]), (original["chat_id"], original["token_fingerprint"]))
            self.assertEqual(statuses[0]["held"], 1)
            self.assertFalse(self.enqueue())
        bot, _transport, _statuses = self.sender_until(lambda state: state["state"] == "DELIVERED")
        bot.send_message.assert_called_once_with(111, "Owner event")

    def test_active_claim_is_not_stolen_by_another_sender(self):
        self.enqueue()
        config = notifications._owner_config()
        row = notifications._claim_next(config, database=self.database)
        self.assertIsNotNone(row)
        self.assertIsNone(notifications._claim_next(config, database=self.database))
        _bot, transport, statuses = self.sender_until(lambda state: state["state"] == "WAITING")
        transport.assert_not_called()
        self.assertEqual(statuses[0]["claimed"], 1)
        self.assertEqual(self.rows()[0]["attempts"], 1)

    def test_expired_interrupted_claim_recovers_after_restart(self):
        self.enqueue()
        config = notifications._owner_config()
        old_claim = notifications._claim_next(config, database=self.database)
        with notifications._connection(self.database) as con:
            con.execute("UPDATE owner_telegram_outbox SET claimed_at=?", (time.time() - notifications.CLAIM_SECONDS - 1,))
        bot, _transport, _statuses = self.sender_until(lambda state: state["state"] == "DELIVERED")
        self.assertEqual(bot.send_message.call_count, 1)
        self.assertEqual((self.rows()[0]["state"], self.rows()[0]["attempts"]), ("SENT", 2))
        with self.assertRaisesRegex(RuntimeError, "claim expired"):
            notifications._mark_sent(old_claim, 999, database=self.database)
        self.assertEqual(self.rows()[0]["message_id"], 42)

    def test_unconfirmed_send_is_retryable_and_not_marked_sent(self):
        self.enqueue()
        bot = Mock()
        # A callable side effect avoids the helper's ordinary successful default.
        bot.send_message.side_effect = lambda *_args: None
        with self.assertLogs(level="WARNING"):
            self.sender_until(lambda state: state["state"] == "ERROR", bot=bot)
        row = self.rows()[0]
        self.assertEqual(row["state"], "RETRY")
        self.assertIn("outcome is unknown", row["last_error"])
        self.assertIsNone(row["message_id"])

    def test_status_write_failure_does_not_break_sender_or_delivery(self):
        self.enqueue()
        stop = threading.Event()
        bot = Mock()
        def delivered(*_args):
            stop.set()
            return 7
        bot.send_message.side_effect = delivered
        with patch.object(notifications, "ClientTelegramBot", return_value=bot), patch.object(notifications, "write_status", side_effect=PermissionError("private")), self.assertLogs(level="WARNING") as logs:
            notifications.run(stop, database=self.database)
        self.assertEqual(self.rows()[0]["state"], "SENT")
        self.assertNotIn("private", str(logs.output))


if __name__ == "__main__":
    unittest.main()
