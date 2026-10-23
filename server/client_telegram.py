from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

from .store import (
    client_by_telegram_chat,
    link_telegram_chat,
    subscription_for_client,
)


class ClientTelegramBot:
    """Client-facing Telegram bot.

    Clients may link their Telegram account and view their own GOLD_AI status.
    Owner/runtime control commands are intentionally not exposed here.
    """

    def __init__(self, token: str | None = None) -> None:
        self.token = (token or os.getenv("GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN", "")).strip()
        self._offset = 0
        self._stop = threading.Event()

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _api(self, method: str, data: Optional[dict] = None, timeout: int = 20) -> Any:
        if not self.configured:
            raise RuntimeError("GOLD_AI client Telegram bot token is not configured.")
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        payload = urllib.parse.urlencode(data or {}).encode()
        request = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

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

            self.send_message(chat_id, reply)
        except Exception as exc:
            try:
                self.send_message(chat_id, f"Could not complete that request: {exc}")
            except Exception:
                pass

    def run_forever(self) -> None:
        if not self.configured:
            print("[CLIENT TELEGRAM] GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN not configured.")
            return

        print("[CLIENT TELEGRAM] Client bot started.")
        while not self._stop.is_set():
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
                for update in (result or {}).get("result", []):
                    self._offset = max(self._offset, int(update["update_id"]) + 1)
                    message = update.get("message")
                    if message:
                        self._handle(message)
            except Exception as exc:
                print(f"[CLIENT TELEGRAM] polling error: {exc}")
                time.sleep(5)

    def stop(self) -> None:
        self._stop.set()


def send_client_message(chat_id: int, text: str) -> Optional[int]:
    return ClientTelegramBot().send_message(chat_id, text)


def main() -> None:
    ClientTelegramBot().run_forever()


if __name__ == "__main__":
    main()
