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
from pathlib import Path
import uuid
from typing import Any, Optional

from .personal_store import write_status
from .store import (
    client_by_telegram_chat,
    link_telegram_chat,
    subscription_for_client,
)


class TelegramRequestError(RuntimeError):
    """A safe, token-free error suitable for logs and service status."""


class TelegramCommandError(ValueError):
    """A bounded user-facing command usage message, never a raw system error."""


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

    Clients may link their Telegram account and view their own AZT status.
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
            raise TelegramRequestError("AZT client Telegram bot token is not configured.")
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

    def send_message(self, chat_id: int, text: str, *, parse_mode: str | None = None) -> Optional[int]:
        if parse_mode and len(str(text).encode('utf-16-le'))//2>4096:
            raise TelegramRequestError('Formatted Telegram message exceeds the delivery limit; split it into pages.')
        data={"chat_id": int(chat_id), "text": str(text)[:4096]}
        if parse_mode:
            data['parse_mode']=parse_mode
        result = self._api(
            "sendMessage",
            data,
        )
        message = (result or {}).get("result", {})
        message_id = message.get("message_id")
        if not isinstance(message_id,int) or isinstance(message_id,bool) or message_id<=0:
            raise TelegramRequestError('Telegram returned no message confirmation; delivery outcome is unknown.')
        return message_id

    def send_photo(self, chat_id: int, path, caption: str = '', *, parse_mode: str | None = None) -> Optional[int]:
        if not self.configured:
            raise TelegramRequestError('Telegram bot token is not configured.')
        boundary='AZT'+uuid.uuid4().hex
        fields=[]
        values=[('chat_id',str(int(chat_id))),('caption',str(caption)[:1024])]
        if parse_mode:
            values.append(('parse_mode',parse_mode))
        for key,value in values:
            fields.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode('utf-8'))
        fields.append((f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="AZT_PnL.png"\r\nContent-Type: image/png\r\n\r\n').encode())
        fields.append(Path(path).read_bytes())
        fields.append(f'\r\n--{boundary}--\r\n'.encode())
        request=urllib.request.Request(f'https://api.telegram.org/bot{self.token}/sendPhoto',data=b''.join(fields),headers={'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
        try:
            with urllib.request.urlopen(request,timeout=20) as response:
                result=json.loads(response.read().decode('utf-8'))
            if not isinstance(result,dict) or result.get('ok') is not True:
                raise TelegramRequestError(_api_error_summary(result.get('error_code',0) if isinstance(result,dict) else 0))
            message_id=result.get('result',{}).get('message_id')
            if not isinstance(message_id,int) or isinstance(message_id,bool) or message_id<=0:
                raise TelegramRequestError('Telegram returned no photo confirmation; delivery outcome is unknown.')
            return message_id
        except TelegramRequestError:
            raise
        except Exception as exc:
            raise TelegramRequestError(_error_summary(exc)) from None

    def _help(self) -> str:
        return (
            "AGORA ZION TRADER • AZT\n\n"
            "/link PAIRING_CODE - link this Telegram to AZT\n"
            "/status - your AZT access status\n"
            "/subscription - subscription/renewal status\n"
            "/positions [page] - detailed open positions and card\n"
            "/journal [YYYY-MM-DD] [page] - daily journal and card\n"
            "/pnl - today's PnL card\n"
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
        photo = None
        photo_caption = ''
        rich_reply = False
        command_client_id = None

        try:
            if command in {"/start", "/help"}:
                reply = self._help()
            elif command == "/link":
                if len(parts) < 2:
                    reply = "Use: /link YOUR_PAIRING_CODE"
                else:
                    client = link_telegram_chat(parts[1], chat_id, username)
                    reply = (
                        f"✅ Telegram linked to AZT client: {client.name}\n"
                        "You can now receive account and subscription notifications."
                    )
            elif command == "/status":
                client = client_by_telegram_chat(chat_id)
                if client is None:
                    reply = "Telegram is not linked yet. Use /link YOUR_PAIRING_CODE."
                else:
                    from .azt_store import subscription_summary
                    access=subscription_summary(client.id)
                    command_client_id=client.id
                    reply = (
                        f"AZT STATUS\n"
                        f"Client: {client.name}\n"
                        f"Access: {client.status} / {access['effective_status']}\n"
                        f"Execution: {client.execution_mode}\n"
                        f"MT5: {client.mt5_login or '-'} @ {client.mt5_server or '-'}"
                    )
            elif command in {'/positions','/journal','/pnl'}:
                client=client_by_telegram_chat(chat_id)
                owner_id=os.getenv('GOLD_AI_OWNER_TELEGRAM_CHAT_ID',os.getenv('TELEGRAM_ADMIN_ID','')).strip()
                owner=client is None and owner_id==str(chat_id)
                if client is None and not owner:
                    reply='Telegram is not linked yet. Use /link YOUR_PAIRING_CODE.'
                else:
                    from .trade_telemetry import list_trades,daily_journal
                    from .pnl_cards import render_positions_cards,render_journal_card
                    from .telegram_presentation import format_positions,format_journal,POSITIONS_PER_PAGE
                    from .workspace_settings import load_settings
                    from .azt_store import preferences
                    scope=None if owner else client.id
                    command_client_id=scope
                    tz=load_settings()['display_timezone'] if owner else preferences(client.id).get('display_timezone','UTC')
                    if command=='/positions':
                        positions=list_trades(scope,state='OPEN')
                        if len(parts)>2:
                            raise TelegramCommandError('Use: /positions [page number]')
                        pages=format_positions(positions,display_timezone=tz)
                        page=self._page_number(parts[1] if len(parts)>1 else '1',len(pages),'/positions')
                        reply=pages[page-1]
                        selected=positions[(page-1)*POSITIONS_PER_PAGE:page*POSITIONS_PER_PAGE]
                        if selected:
                            rendered=render_positions_cards(selected,display_timezone=tz)
                            photo=rendered[0] if rendered else None
                            photo_caption=f'AZT • Open positions • Page {page}/{len(pages)}\nFull position details and currency totals are in the message above.'
                    else:
                        from datetime import datetime
                        from zoneinfo import ZoneInfo
                        arguments=parts[1:]
                        date=datetime.now(ZoneInfo(tz)).date().isoformat()
                        if arguments and '-' in arguments[0]:
                            from datetime import date as date_type
                            try:
                                value=arguments.pop(0)
                                if len(value)!=10:
                                    raise ValueError
                                date=date_type.fromisoformat(value).isoformat()
                            except ValueError:
                                raise TelegramCommandError('Use a valid local date: /journal YYYY-MM-DD [page number]') from None
                        if len(arguments)>1:
                            raise TelegramCommandError('Use: /journal [YYYY-MM-DD] [page number]')
                        journal=daily_journal(scope,date=date,timezone=tz)
                        pages=format_journal(journal,display_timezone=tz)
                        page=self._page_number(arguments[0] if arguments else '1',len(pages),'/journal '+date)
                        reply=pages[page-1]
                        if page==1:
                            photo=render_journal_card(journal,display_timezone=tz)
                            photo_caption=f'AZT • Daily journal • {date} • {tz}\nThe complete summary and trade details are in the message above.'
                    rich_reply=True
            elif command == "/subscription":
                client = client_by_telegram_chat(chat_id)
                if client is None:
                    reply = "Telegram is not linked yet. Use /link YOUR_PAIRING_CODE."
                else:
                    from .azt_store import subscription_summary,preferences
                    from .trade_telemetry import display_time
                    summary=subscription_summary(client.id)
                    sub=summary['subscription']
                    tz=preferences(client.id)['display_timezone']
                    command_client_id=client.id
                    reply = (
                        f"AZT SUBSCRIPTION\n"
                        f"Plan: {sub['plan_code']}\n"
                        f"Status: {summary['effective_status']}\n"
                        f"Expires: {display_time(sub['expires_utc'],tz)} ({tz})\n"
                        "Use the AZT Payments page to renew."
                    )
            else:
                reply = self._help()

        except Exception as exc:
            # Only the known user-facing validation message is safe to echo.
            detail = str(exc) if isinstance(exc,TelegramCommandError) else "Invalid pairing code." if isinstance(exc, ValueError) and str(exc) == "Invalid pairing code." else "Please try again later."
            reply = f"Could not complete that request: {detail}"

        # A failed reply must not replay a command that may already have changed
        # the database, or trigger a second fallback send with an uncertain result.
        try:
            if rich_reply:
                self.send_message(chat_id, reply, parse_mode='HTML')
                if photo:
                    self.send_photo(chat_id,photo,photo_caption)
            elif photo:
                self.send_photo(chat_id, photo, reply)
            else:
                self.send_message(chat_id, reply)
        except Exception as exc:
            summary = _error_summary(exc)
            if self.token:
                summary = summary.replace(self.token, "[redacted]")
            self._last_reply_error = re.sub(r"https?://\S+", "[redacted URL]", summary)[:500]
            self._record_command(command,'FAILED',command_client_id)
            raise TelegramRequestError(self._last_reply_error) from None
        self._last_reply_error = None
        self._record_command(command,'REPLIED',command_client_id)

    @staticmethod
    def _page_number(value, count, command):
        try:
            page=int(value)
        except (ValueError,TypeError):
            raise TelegramCommandError(f'Use: {command} [page number]') from None
        if not 1 <= page <= count:
            raise TelegramCommandError(f'Choose a page from 1 to {count}. Example: {command} 1')
        return page

    def _record_command(self,command,state,client_id=None):
        from .client_notifications import record_command
        record_command(command if command.startswith('/') else '(help)',state,client_id)

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
