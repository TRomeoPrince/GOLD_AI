"""Durable outbound-only owner alerts, independent of order execution.

The outbox deduplicates event creation and never reroutes a recorded event to a
different chat or token. It cannot promise exactly-once remote delivery: a network
timeout, or a crash after Telegram accepts a message but before the SENT commit,
can leave an ambiguous outcome. Expired claims are retried at most five times.
No command polling or trading control is implemented here.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import logging
import os
import re
import sqlite3
import time
import uuid

from .client_telegram import ClientTelegramBot, TelegramRequestError, _error_summary
from .personal_store import write_status
from .store import DB_PATH


MAX_ATTEMPTS = 5
CLAIM_SECONDS = 60
MAX_BACKOFF_SECONDS = 120


@dataclass(frozen=True)
class OwnerConfig:
    token: str = field(repr=False)
    chat_id: int
    fingerprint: str


def _owner_config():
    if os.getenv("GOLD_AI_OWNER_TELEGRAM_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return None
    token = next((os.getenv(key, "").strip() for key in (
        "GOLD_AI_OWNER_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN",
        "GOLD_AI_CLIENT_TELEGRAM_BOT_TOKEN",
    ) if os.getenv(key, "").strip()), "")
    chat = next((os.getenv(key, "").strip() for key in (
        "GOLD_AI_OWNER_TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_ID",
    ) if os.getenv(key, "").strip()), "")
    # Reject placeholders, URLs and malformed destination IDs; never guess a chat
    # from the customer list, MT5 account, Telegram username or another recipient.
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", token):
        return None
    if len(chat) > 20 or not re.fullmatch(r"-?[0-9]+", chat):
        return None
    chat_id = int(chat)
    if not chat_id or abs(chat_id) > 2**63 - 1:
        return None
    return OwnerConfig(token, chat_id, hashlib.sha256(token.encode("utf-8")).hexdigest())


@contextmanager
def _connection(database=None):
    # Keep a busy outbox from holding up the trading worker. Notification failure
    # never rolls back or prevents a trade/journal update made by the caller.
    con = sqlite3.connect(database if database is not None else DB_PATH, timeout=.25)
    con.row_factory = sqlite3.Row
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS owner_telegram_outbox (
            event_key TEXT PRIMARY KEY,
            message TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            token_fingerprint TEXT NOT NULL,
            created REAL NOT NULL,
            updated REAL NOT NULL,
            state TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL DEFAULT 0,
            claimed_at REAL,
            claim_id TEXT,
            message_id INTEGER,
            last_error TEXT NOT NULL DEFAULT ''
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS owner_telegram_pending ON owner_telegram_outbox(state,next_attempt)")
        con.commit()
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def enqueue_owner_event(event_key, text, *, database=None) -> bool:
    """Only persist an event. Never contact Telegram or propagate queue errors."""
    try:
        config = _owner_config()
        if config is None:
            return False
        key, message = str(event_key).strip(), str(text).strip()
        if not key or len(key) > 500 or not message:
            return False
        now = time.time()
        with _connection(database) as con:
            return con.execute(
                "INSERT OR IGNORE INTO owner_telegram_outbox(event_key,message,chat_id,token_fingerprint,created,updated) VALUES(?,?,?,?,?,?)",
                (key, message[:4096], config.chat_id, config.fingerprint, now, now),
            ).rowcount == 1
    except Exception as exc:
        # No payload, destination, raw exception or token-bearing URL in the log.
        logging.warning("Owner Telegram event could not be queued (%s).", type(exc).__name__)
        return False


def _claim_next(config, *, database=None, now=None):
    now = time.time() if now is None else now
    with _connection(database) as con:
        con.execute("BEGIN IMMEDIATE")
        # A lease prevents a second sender from stealing an active request. A
        # crashed sender's claim becomes retryable after this bounded interval.
        con.execute(
            "UPDATE owner_telegram_outbox SET state=CASE WHEN attempts>=? THEN 'FAILED' ELSE 'RETRY' END,next_attempt=?,updated=?,claim_id=NULL,claimed_at=NULL,last_error=? WHERE state='CLAIMED' AND (claimed_at IS NULL OR claimed_at<=?)",
            (MAX_ATTEMPTS, now, now, "Interrupted sender claim; previous delivery outcome may be unknown.", now-CLAIM_SECONDS),
        )
        con.execute(
            "UPDATE owner_telegram_outbox SET state='HELD',updated=?,last_error=? WHERE state IN ('PENDING','RETRY') AND (chat_id<>? OR token_fingerprint<>?)",
            (now, "Configuration changed; event held for its original owner destination.", config.chat_id, config.fingerprint),
        )
        con.execute(
            "UPDATE owner_telegram_outbox SET state=CASE WHEN attempts=0 THEN 'PENDING' ELSE 'RETRY' END,updated=?,last_error='' WHERE state='HELD' AND chat_id=? AND token_fingerprint=?",
            (now, config.chat_id, config.fingerprint),
        )
        row = con.execute(
            "SELECT * FROM owner_telegram_outbox WHERE state IN ('PENDING','RETRY') AND attempts<? AND next_attempt<=? AND chat_id=? AND token_fingerprint=? ORDER BY created,event_key LIMIT 1",
            (MAX_ATTEMPTS, now, config.chat_id, config.fingerprint),
        ).fetchone()
        if row is None:
            return None
        claim = uuid.uuid4().hex
        con.execute(
            "UPDATE owner_telegram_outbox SET state='CLAIMED',attempts=attempts+1,claimed_at=?,claim_id=?,updated=? WHERE event_key=?",
            (now, claim, now, row["event_key"]),
        )
        result = dict(row)
        result.update(state="CLAIMED", attempts=int(row["attempts"])+1, claimed_at=now, claim_id=claim)
        return result


def _mark_sent(row, message_id, *, database=None):
    with _connection(database) as con:
        changed = con.execute(
            "UPDATE owner_telegram_outbox SET state='SENT',message_id=?,updated=?,claim_id=NULL,claimed_at=NULL,last_error='' WHERE event_key=? AND state='CLAIMED' AND claim_id=?",
            (message_id, time.time(), row["event_key"], row["claim_id"]),
        ).rowcount
    if not changed:
        raise RuntimeError("Owner notification claim expired before confirmation was recorded.")


def _mark_failed(row, error, *, database=None):
    attempts = int(row["attempts"])
    state = "FAILED" if attempts >= MAX_ATTEMPTS else "RETRY"
    delay = min(5 * 2 ** (attempts-1), MAX_BACKOFF_SECONDS)
    now = time.time()
    with _connection(database) as con:
        changed = con.execute(
            "UPDATE owner_telegram_outbox SET state=?,next_attempt=?,updated=?,last_error=?,claim_id=NULL,claimed_at=NULL WHERE event_key=? AND state='CLAIMED' AND claim_id=?",
            (state, now+delay, now, error[:500], row["event_key"], row["claim_id"]),
        ).rowcount
    if not changed:
        raise RuntimeError("Owner notification claim expired before its failure was recorded.")
    return state


def _safe_error(exc, token):
    summary = _error_summary(exc)
    if token:
        summary = summary.replace(token, "[redacted]")
    return re.sub(r"https?://\S+", "[redacted URL]", summary)[:500]


def _status(state, message, **values):
    try:
        write_status("notifications", state=state, message=message, **values)
    except Exception as exc:
        logging.warning("Owner Telegram status could not be written (%s).", type(exc).__name__)


def _idle_status(config, database):
    with _connection(database) as con:
        held = con.execute("SELECT count(*) FROM owner_telegram_outbox WHERE state='HELD'").fetchone()[0]
        counts = dict(con.execute("SELECT state,count(*) FROM owner_telegram_outbox WHERE chat_id=? AND token_fingerprint=? GROUP BY state", (config.chat_id, config.fingerprint)).fetchall())
        last = con.execute("SELECT last_error FROM owner_telegram_outbox WHERE chat_id=? AND token_fingerprint=? AND last_error<>'' ORDER BY updated DESC LIMIT 1", (config.chat_id, config.fingerprint)).fetchone()
    stats = {
        "delivered": counts.get("SENT", 0), "pending": counts.get("PENDING", 0),
        "retrying": counts.get("RETRY", 0), "failed": counts.get("FAILED", 0),
        "claimed": counts.get("CLAIMED", 0), "held": held,
    }
    error = _safe_error(TelegramRequestError(last["last_error"]), config.token) if last else ""
    summary = "Owner alerts: " + ", ".join(f"{value} {key}" for key, value in stats.items()) + "."
    if stats["failed"]:
        state = "FAILED"
    elif stats["retrying"]:
        state = "RETRYING"
    elif stats["claimed"]:
        state = "WAITING"
        summary += " Delivery claim active; interrupted claims recover after the lease expires."
    elif held:
        state = "HELD"
        summary += " Alerts are held for their original owner configuration and are not rerouted."
    elif stats["pending"]:
        state = "WAITING"
    else:
        state = "IDLE"
    if error:
        summary += " Last issue: " + error
    return state, summary, stats


def run(stop, *, database=None):
    """Run in the separate hidden sender process; never poll getUpdates."""
    if _owner_config() is None:
        _status("NOT_CONFIGURED", "Set an owner bot token and numeric owner chat ID, or enable owner alerts.")
        return
    try:
        while not stop.is_set():
            config = _owner_config()
            if config is None:
                _status("NOT_CONFIGURED", "Owner alerts disabled or owner configuration is invalid.")
                stop.wait(5)
                continue
            try:
                row = _claim_next(config, database=database)
            except Exception as exc:
                logging.warning("Owner Telegram outbox unavailable (%s).", type(exc).__name__)
                _status("ERROR", "Owner alert queue is unavailable; retrying.")
                stop.wait(5)
                continue
            if row is None:
                try:
                    state, message, stats = _idle_status(config, database)
                except Exception:
                    state, message, stats = "ERROR", "Owner alert queue summary is unavailable.", {}
                _status(state, message, **stats)
                stop.wait(1)
                continue
            _status("SENDING", f"Sending owner alert, attempt {row['attempts']} of {MAX_ATTEMPTS}.")
            try:
                message_id = ClientTelegramBot(token=config.token).send_message(row["chat_id"], row["message"])
                if not isinstance(message_id, int) or message_id <= 0:
                    raise TelegramRequestError("Telegram returned no message confirmation; delivery outcome is unknown.")
            except Exception as exc:
                error = _safe_error(exc, config.token)
                try:
                    state = _mark_failed(row, error, database=database)
                    detail = "Retry queued." if state == "RETRY" else "Retry limit reached; alert marked FAILED."
                except Exception as journal_exc:
                    logging.warning("Owner Telegram retry journal unavailable (%s).", type(journal_exc).__name__)
                    detail = "Claim retained for recovery; delivery outcome may be unknown."
                logging.warning("Owner Telegram delivery failed: %s", error)
                _status("ERROR", error + " " + detail)
                stop.wait(.2)
                continue
            try:
                _mark_sent(row, message_id, database=database)
            except Exception as exc:
                logging.warning("Owner Telegram confirmation journal unavailable (%s).", type(exc).__name__)
                _status("ERROR", "Telegram accepted the alert, but its confirmation could not be recorded; delivery outcome needs review.")
            else:
                _status("DELIVERED", f"Owner alert delivered (message {message_id}).", message_id=message_id)
            stop.wait(1)
    finally:
        _status("STOPPED", "Owner alert sender stopped; queued events remain saved.")
