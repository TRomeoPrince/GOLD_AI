import json
import socket
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server import client_telegram as telegram


class TelegramAPITests(unittest.TestCase):
    def setUp(self):
        self.bot = telegram.ClientTelegramBot(token="test-secret-token")

    def response(self, payload):
        response = Mock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context

    def test_successful_bot_api_response_and_send_id(self):
        with patch.object(telegram.urllib.request, "urlopen", return_value=self.response({"ok": True, "result": {"message_id": 123}})) as network:
            self.assertEqual(self.bot.send_message(1, "Mocked test"), 123)
        self.assertEqual(network.call_count, 1)

    def test_error_json_is_not_silent_success_and_description_is_not_exposed(self):
        payload = {"ok": False, "error_code": 401, "description": "bad token test-secret-token https://api.telegram.org/bottest-secret-token/getUpdates"}
        with patch.object(telegram.urllib.request, "urlopen", return_value=self.response(payload)):
            with self.assertRaises(telegram.TelegramRequestError) as caught:
                self.bot._api("getUpdates")
        self.assertIn("401", str(caught.exception))
        self.assertNotIn(self.bot.token, str(caught.exception))
        self.assertNotIn("https://", str(caught.exception))

    def test_non_dictionary_or_missing_ok_response_is_rejected(self):
        for payload in ([], {"result": []}, {"ok": 1, "result": []}):
            with self.subTest(payload=payload), patch.object(telegram.urllib.request, "urlopen", return_value=self.response(payload)):
                with self.assertRaises(telegram.TelegramRequestError):
                    self.bot._api("getUpdates")

    def test_http_conflict_summary_does_not_include_token_url(self):
        error = urllib.error.HTTPError(
            "https://api.telegram.org/bottest-secret-token/getUpdates", 409,
            "test-secret-token", None, None,
        )
        with patch.object(telegram.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(telegram.TelegramRequestError) as caught:
                self.bot._api("getUpdates")
        self.assertIn("409", str(caught.exception))
        self.assertNotIn(self.bot.token, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_dns_error_summary_does_not_echo_exception_text(self):
        error = urllib.error.URLError(socket.gaierror(11001, "DNS failed https://api.telegram.org/bottest-secret-token/getUpdates"))
        with patch.object(telegram.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(telegram.TelegramRequestError) as caught:
                self.bot._api("getUpdates")
        self.assertIn("DNS", str(caught.exception))
        self.assertNotIn(self.bot.token, str(caught.exception))

    def test_invalid_json_is_safely_reported(self):
        response = Mock()
        response.read.return_value = b"not JSON test-secret-token"
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch.object(telegram.urllib.request, "urlopen", return_value=context):
            with self.assertRaisesRegex(telegram.TelegramRequestError, "invalid JSON") as caught:
                self.bot._api("getUpdates")
        self.assertNotIn(self.bot.token, str(caught.exception))


class TelegramWorkerTests(unittest.TestCase):
    def setUp(self):
        self.bot = telegram.ClientTelegramBot(token="test-secret-token")
        self.status_patch = patch.object(telegram, "write_status")
        self.status = self.status_patch.start()
        self.print_patch = patch("builtins.print")
        self.print = self.print_patch.start()

    def tearDown(self):
        self.print_patch.stop()
        self.status_patch.stop()

    def states(self):
        return [call.kwargs["state"] for call in self.status.call_args_list]

    def test_missing_token_reports_not_configured_without_network(self):
        with patch.dict("os.environ", {"GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN": ""}):
            bot = telegram.ClientTelegramBot()
        with patch.object(bot, "_api") as network:
            bot.run_forever()
        self.assertEqual(self.states(), ["NOT_CONFIGURED"])
        network.assert_not_called()

    def test_successful_poll_reports_connectivity_and_stops_cleanly(self):
        def poll(*_args, **_kwargs):
            self.bot.stop()
            return {"ok": True, "result": []}
        with patch.object(self.bot, "_api", side_effect=poll) as network:
            self.bot.run_forever()
        self.assertEqual(self.states(), ["CONNECTING", "CONNECTED", "STOPPED"])
        self.assertEqual(network.call_count, 1)

    def test_retry_wait_is_interruptible_and_error_status_is_sanitized(self):
        error = urllib.error.URLError(socket.gaierror(11001, "test-secret-token in a URL"))
        with patch.object(self.bot, "_api", side_effect=error), patch.object(self.bot._stop, "wait", side_effect=lambda _seconds: self.bot.stop()) as wait:
            self.bot.run_forever()
        self.assertEqual(self.states(), ["CONNECTING", "ERROR", "STOPPED"])
        wait.assert_called_once_with(5)
        error_status = self.status.call_args_list[1].kwargs["message"]
        self.assertIn("DNS", error_status)
        self.assertNotIn(self.bot.token, error_status)
        self.assertNotIn(self.bot.token, str(self.print.call_args_list))

    def test_polling_still_dispatches_messages_and_advances_offset(self):
        message = {"chat": {"id": 1}, "text": "/help"}
        def poll(*_args, **_kwargs):
            self.bot.stop()
            return {"ok": True, "result": [{"update_id": 44, "message": message}]}
        with patch.object(self.bot, "_api", side_effect=poll), patch.object(self.bot, "_handle") as handle:
            self.bot.run_forever()
        handle.assert_called_once_with(message)
        self.assertEqual(self.bot._offset, 45)

    def test_link_command_preserves_existing_routing_without_real_send_or_db(self):
        message = {"chat": {"id": 123}, "from": {"username": "example"}, "text": "/link PAIR-CODE"}
        with patch.object(telegram, "link_telegram_chat", return_value=SimpleNamespace(name="Demo")) as link, patch.object(self.bot, "send_message") as send:
            self.bot._handle(message)
        link.assert_called_once_with("PAIR-CODE", 123, "example")
        self.assertEqual(send.call_args.args[0], 123)
        self.assertIn("Demo", send.call_args.args[1])

    def test_failed_link_reply_is_surfaced_without_replaying_link_or_fallback_send(self):
        message = {"chat": {"id": 123}, "from": {"username": "example"}, "text": "/link PAIR-CODE"}
        error = telegram.TelegramRequestError("Failed test-secret-token https://api.telegram.org/bottest-secret-token/sendMessage")
        with patch.object(telegram, "link_telegram_chat", return_value=SimpleNamespace(name="Demo")) as link, patch.object(self.bot, "send_message", side_effect=error) as send:
            with self.assertRaises(telegram.TelegramRequestError) as caught:
                self.bot._handle(message)
        link.assert_called_once_with("PAIR-CODE", 123, "example")
        send.assert_called_once()
        self.assertEqual(self.bot._last_reply_error, str(caught.exception))
        self.assertNotIn(self.bot.token, str(caught.exception))
        self.assertNotIn("https://", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_failed_reply_stays_visible_after_a_successful_empty_poll(self):
        message = {"chat": {"id": 1}, "text": "/help"}
        polls = [0]
        def poll(*_args, **_kwargs):
            polls[0] += 1
            if polls[0] == 1:
                return {"ok": True, "result": [{"update_id": 44, "message": message}]}
            self.bot.stop()
            return {"ok": True, "result": []}
        with patch.object(self.bot, "_api", side_effect=poll) as network, patch.object(self.bot, "send_message", side_effect=TimeoutError("private token URL")) as send, patch.object(self.bot._stop, "wait", return_value=False):
            self.bot.run_forever()
        self.assertEqual(self.states(), ["CONNECTING", "CONNECTED", "REPLY_ERROR", "REPLY_ERROR", "STOPPED"])
        self.assertEqual(self.bot._offset, 45)
        self.assertEqual(network.call_args_list[1].args[1]["offset"], 45)
        send.assert_called_once()
        self.assertIsNotNone(self.bot._last_reply_error)

    def test_later_successful_reply_clears_the_previous_reply_error(self):
        message = {"chat": {"id": 1}, "text": "/help"}
        polls = [0]
        def poll(*_args, **_kwargs):
            polls[0] += 1
            if polls[0] == 2:
                self.assertEqual(self.states()[-1], "REPLY_ERROR")
                self.bot.stop()
            return {"ok": True, "result": [{"update_id": 43 + polls[0], "message": message}]}
        with patch.object(self.bot, "_api", side_effect=poll), patch.object(self.bot, "send_message", side_effect=[TimeoutError(), 123]) as send, patch.object(self.bot._stop, "wait", return_value=False):
            self.bot.run_forever()
        self.assertEqual(self.states(), ["CONNECTING", "CONNECTED", "REPLY_ERROR", "REPLY_ERROR", "CONNECTED", "STOPPED"])
        self.assertEqual(send.call_count, 2)
        self.assertIsNone(self.bot._last_reply_error)
        self.assertEqual(self.bot._offset, 46)

    def test_domain_validation_reply_is_preserved_but_private_errors_are_not_echoed(self):
        message = {"chat": {"id": 123}, "text": "/link BAD"}
        for error, expected in ((ValueError("Invalid pairing code."), "Invalid pairing code."), (OSError("private database path"), "Please try again later.")):
            with self.subTest(error=type(error).__name__), patch.object(telegram, "link_telegram_chat", side_effect=error) as link, patch.object(self.bot, "send_message") as send:
                self.bot._handle(message)
            link.assert_called_once()
            send.assert_called_once_with(123, "Could not complete that request: " + expected)

    def test_status_write_failure_cannot_stop_polling_or_reply_delivery(self):
        message = {"chat": {"id": 1}, "text": "/help"}
        def poll(*_args, **_kwargs):
            self.bot.stop()
            return {"ok": True, "result": [{"update_id": 44, "message": message}]}
        self.status.side_effect = PermissionError("private status path")
        with patch.object(self.bot, "_api", side_effect=poll), patch.object(self.bot, "send_message", return_value=123) as send, self.assertLogs(level="WARNING") as logs:
            self.bot.run_forever()
        send.assert_called_once()
        self.assertEqual(self.bot._offset, 45)
        self.assertIsNone(self.bot._last_reply_error)
        self.assertEqual(self.states(), ["CONNECTING", "CONNECTED", "CONNECTED", "STOPPED"])
        self.assertNotIn("private status path", str(logs.output))


if __name__ == "__main__":
    unittest.main()
