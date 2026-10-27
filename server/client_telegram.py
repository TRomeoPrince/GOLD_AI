from __future__ import annotations

import json
import logging
import os
import re
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from .personal_store import write_status
from .store import (
    client_by_telegram_chat,
    link_telegram_chat,
    subscription_for_client,
)


class TelegramRequestError(RuntimeError):
    """A safe, token-free error suitable for logs and service status."""


def _api_error_summary(code: int) -> str:
    summaries = {
        401: "Telegram rejected the bot token (HTTP 401).",
        403: "Telegram denied access (HTTP 403).",
        409: "Telegram polling conflict: another bot instance or webhook is active (HTTP 409).",
        429: "Telegram rate limit reached (HTTP 429).",
    }
    return summaries.get(code, f"Telegram rejected the request (HTTP {code})." if code else "Telegram returned an unsuccessful Bot API response.")


def _error_summary(exc: BaseException) -> str:
    # Do not interpolate network exception text: it can include the token URL.
    if isinstance(exc, TelegramRequestError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        return _api_error_summary(exc.code)
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return _error_summary(reason) if isinstance(reason, BaseException) else "Could not connect to Telegram. Check the network connection."
    if isinstance(exc, socket.gaierror):
        return "Telegram DNS lookup failed. Check the network connection."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "Telegram connection or response timed out."
    if isinstance(exc, ssl.SSLError):
        return "Telegram TLS connection failed."
    if isinstance(exc, ConnectionError):
        return "Telegram network connection was interrupted."
    if isinstance(exc, (json.JSONDecodeError, UnicodeError)):
        return "Telegram returned an invalid JSON response."
    return f"Telegram request failed ({type(exc).__name__})."


def _status(state: str, message: str) -> None:
    try:
        write_status("telegram", state=state, message=message)
    except Exception as exc:
        logging.warning("Telegram status could not be written (%s).", type(exc).__name__)


class ClientTelegramBot:
    """Client-facing Telegram bot.

    Clients may link their Telegram account and view their own GOLD_AI status.
    Owner/runtime control commands are intentionally not exposed here.
    """

    def __init__(self, token: str | None = None) -> None:
        self.token = (token or os.getenv("GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN", "")).strip()
        self._offset = 0
        self._stop = threading.Event()
        self._last_reply_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _api(self, method: str, data: Optional[dict] = None, timeout: int = 20) -> Any:
        if not self.configured:
            raise TelegramRequestError("GOLD_AI client Telegram bot token is not configured.")
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        payload = urllib.parse.urlencode(data or {}).encode()
        request = urllib.request.Request(url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict) or result.get("ok") is not True:
                code = result.get("error_code", 0) if isinstance(result, dict) else 0
                code = code if isinstance(code, int) else 0
                raise TelegramRequestError(_api_error_summary(code))
            return result
        except TelegramRequestError:
            raise
        except Exception as exc:
            raise TelegramRequestError(_error_summary(exc)) from None

    def send_message(self, chat_id: int, text: str) -> Optional[int]:
        result = self._api(
            "sendMessage",
            {"chat_id": int(chat_id), "text": str(text)[:4096]},
        )
        message = (result or {}).get("result", {})
        message_id = message.get("message_id")
        return int(message_id) if message_id is not None else None

    def _help(self) -> str:
        return (
            "GOLD_AI Client Bot\n\n"
            "/link PAIRING_CODE - link this Telegram to GOLD_AI\n"
            "/status - your GOLD_AI access status\n"
            "/subscription - subscription/renewal status\n"
            "/help - show commands"
        )

    def _handle(self, message: dict) -> None:
        chat_id = int(message.get("chat", {}).get("id", 0) or 0)
        username = str(message.get("from", {}).get("username", "") or "")
        text = str(message.get("text", "") or "").strip()
        if not chat_id or not text:
            return

        parts = text.split()
        command = parts[0].split("@")[0].lower() if parts else ""

        try:
            if command in {"/start", "/help"}:
                reply = self._help()
            elif command == "/link":
                if len(parts) < 2:
                    reply = "Use: /link YOUR_PAIRING_CODE"
                else:
                    client = link_telegram_chat(parts[1], chat_id, username)
                    reply = (
                        f"✅ Telegram linked to GOLD_AI client: {client.name}\n"
                        "You can now receive account and subscription notifications."
                    )
            elif command == "/status":
                client = client_by_telegram_chat(chat_id)
                if client is None:
                    reply = "Telegram is not linked yet. Use /link YOUR_PAIRING_CODE."
                else:
                    reply = (
                        f"GOLD_AI STATUS\n"
                        f"Client: {client.name}\n"
                        f"Access: {client.status}\n"
                        f"Execution: {client.execution_mode}\n"
                        f"MT5: {client.mt5_login or '-'} @ {client.mt5_server or '-'}"
                    )
            elif command == "/subscription":
                client = client_by_telegram_chat(chat_id)
                if client is None:
                    reply = "Telegram is not linked yet. Use /link YOUR_PAIRING_CODE."
                else:
                    sub = subscription_for_client(client.id)
                    reply = (
                        f"GOLD_AI SUBSCRIPTION\n"
                        f"Plan: {sub['plan_code']}\n"
                        f"Status: {sub['status']}\n"
                        f"Expires: {sub['expires_utc'] or 'Not set'}\n"
                        "Use the GOLD_AI app/dashboard to renew."
                    )
            else:
                reply = self._help()

        except Exception as exc:
            # Only the known user-facing validation message is safe to echo.
            detail = "Invalid pairing code." if isinstance(exc, ValueError) and str(exc) == "Invalid pairing code." else "Please try again later."
            reply = f"Could not complete that request: {detail}"

        # A failed reply must not replay a command that may already have changed
        # the database, or trigger a second fallback send with an uncertain result.
        try:
            self.send_message(chat_id, reply)
        except Exception as exc:
            summary = _error_summary(exc)
            if self.token:
                summary = summary.replace(self.token, "[redacted]")
            self._last_reply_error = re.sub(r"https?://\S+", "[redacted URL]", summary)[:500]
            raise TelegramRequestError(self._last_reply_error) from None
        self._last_reply_error = None

    def _report_connection(self) -> None:
        if self._last_reply_error:
            _status("REPLY_ERROR", "Connected to Telegram, but the last command reply failed: " + self._last_reply_error)
        else:
            _status("CONNECTED", "Connected to Telegram; listening for client commands.")

    def run_forever(self) -> None:
        if not self.configured:
            _status("NOT_CONFIGURED", "Set GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN in the project .env.")
            print("[CLIENT TELEGRAM] GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN not configured.")
            return

        _status("CONNECTING", "Connecting to Telegram.")
        print("[CLIENT TELEGRAM] Client bot started.")
        try:
            while not self._stop.is_set():
                handling_reply = False
                try:
                    result = self._api(
                        "getUpdates",
                        {
                            "offset": self._offset,
                            "timeout": 15,
                            "allowed_updates": json.dumps(["message"]),
                        },
                        timeout=20,
                    )
                    self._report_connection()
                    for update in (result or {}).get("result", []):
                        self._offset = max(self._offset, int(update["update_id"]) + 1)
                        message = update.get("message")
                        if message:
                            handling_reply = True
                            self._handle(message)
                            handling_reply = False
                            self._report_connection()
                except Exception as exc:
                    summary = _error_summary(exc)
                    state = "REPLY_ERROR" if handling_reply and self._last_reply_error else "ERROR"
                    _status(state, summary)
                    print(f"[CLIENT TELEGRAM] {'reply' if handling_reply else 'polling'} error: {summary}")
                    self._stop.wait(5)
        finally:
            _status("STOPPED", "Telegram service stopped.")

    def stop(self) -> None:
        self._stop.set()


def send_client_message(chat_id: int, text: str) -> Optional[int]:
    return ClientTelegramBot().send_message(chat_id, text)


def main() -> None:
    ClientTelegramBot().run_forever()


if __name__ == "__main__":
    main()
