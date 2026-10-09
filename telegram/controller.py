from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class RuntimeState:
    paused: bool = False
    stop_requested: bool = False


class TelegramController:
    """Telegram notification/control layer.

    Trading never depends on Telegram availability. Commands are accepted only
    from the configured admin user ID. /stop stops the Python runtime but does
    not close MT5 positions; broker-side SL/TP remain in place.
    """

    def __init__(self, token: str, admin_id: int) -> None:
        self.token = token.strip()
        self.admin_id = int(admin_id)
        self.state = RuntimeState()
        self._offset = 0
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {}
        self._positions_text = "No position snapshot yet."
        self._journal_text = "No journal events yet."

    @property
    def configured(self) -> bool:
        return bool(self.token and self.admin_id)

    def _api(self, method: str, data: Optional[dict] = None, timeout: int = 15) -> Any:
        if not self.configured:
            return None
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        payload = urllib.parse.urlencode(data or {}).encode()
        request = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def notify(self, text: str) -> bool:
        try:
            self._api("sendMessage", {"chat_id": self.admin_id, "text": text})
            return True
        except Exception as exc:
            print(f"[TELEGRAM] notification failed: {exc}")
            return False

    def update_snapshot(
        self,
        *,
        status: Optional[dict] = None,
        positions_text: Optional[str] = None,
        journal_text: Optional[str] = None,
    ) -> None:
        with self._lock:
            if status is not None:
                self._status = dict(status)
            if positions_text is not None:
                self._positions_text = positions_text
            if journal_text is not None:
                self._journal_text = journal_text

    def _status_text(self) -> str:
        with self._lock:
            snap = dict(self._status)
        mode = "PAUSED" if self.state.paused else "RUNNING"
        if self.state.stop_requested:
            mode = "STOPPING"
        lines = [
            "GOLD_AI STATUS",
            f"Runtime: {mode}",
            f"Account: {snap.get('account', '-')}",
            f"Symbol: {snap.get('symbol', '-')}",
            f"Balance: {snap.get('balance', '-')}",
            f"Equity: {snap.get('equity', '-')}",
            f"Open GOLD_AI positions: {snap.get('positions', 0)}",
        ]
        return "\n".join(lines)

    def _handle(self, message: dict) -> None:
        sender = int(message.get("from", {}).get("id", 0) or 0)
        chat_id = int(message.get("chat", {}).get("id", 0) or 0)
        text = str(message.get("text", "")).strip()
        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""

        if sender != self.admin_id:
            if command:
                try:
                    self._api("sendMessage", {"chat_id": chat_id, "text": "⛔ Unauthorized."})
                except Exception:
                    pass
            return

        if command in ("/start", "/help"):
            reply = (
                "GOLD_AI Telegram Control\n"
                "/status - runtime/account status\n"
                "/positions - cached open positions\n"
                "/journal - latest journal event\n"
                "/pause - block NEW entries only\n"
                "/resume - allow new entries\n"
                "/stop - stop GOLD_AI runtime; does NOT close positions"
            )
        elif command == "/pause":
            self.state.paused = True
            reply = "⏸ GOLD_AI PAUSED. New entries are blocked. Existing MT5 positions are not closed."
        elif command == "/resume":
            self.state.paused = False
            reply = "▶️ GOLD_AI RESUMED. New entries are enabled."
        elif command == "/stop":
            self.state.stop_requested = True
            reply = "🛑 GOLD_AI stop requested. No positions will be closed by this command."
        elif command == "/status":
            reply = self._status_text()
        elif command == "/positions":
            with self._lock:
                reply = self._positions_text
        elif command == "/journal":
            with self._lock:
                reply = self._journal_text
        else:
            reply = "Unknown command. Use /help."

        try:
            self._api("sendMessage", {"chat_id": chat_id, "text": reply})
        except Exception as exc:
            print(f"[TELEGRAM] reply failed: {exc}")

    def _poll(self) -> None:
        while not self.state.stop_requested:
            try:
                result = self._api(
                    "getUpdates",
                    {"offset": self._offset, "timeout": 10, "allowed_updates": json.dumps(["message"])},
                    timeout=15,
                )
                for update in (result or {}).get("result", []):
                    self._offset = max(self._offset, int(update["update_id"]) + 1)
                    message = update.get("message")
                    if message:
                        self._handle(message)
            except Exception as exc:
                print(f"[TELEGRAM] polling error: {exc}")
                time.sleep(5)

    def start(self) -> None:
        if not self.configured:
            return
        self._thread = threading.Thread(target=self._poll, name="gold-ai-telegram", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.state.stop_requested = True
