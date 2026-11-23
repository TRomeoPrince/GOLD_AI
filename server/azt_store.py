"""AZT business records. All writes are local, transactional and additive.

Public HTTP routes expose client-scoped readers/actions only. Owner actions such
as approving payments remain local Admin calls, never unauthenticated web APIs.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import base64
import json
import math
import re
import secrets
import io
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
PAYMENT_WARNING = "Send only using the exact network shown. Payments sent using the wrong network may not be recoverable."
PAYMENT_METHODS = (
    {"code": "MTN", "name": "MTN Mobile Money", "network": "MTN Mobile Money Uganda", "address": "0781920398", "recipient": "ROMEO", "verification": "MANUAL_PROOF"},
    {"code": "USDT_TRC20", "name": "USDT", "network": "TRC20 / Tron", "address": "TCcR54xQu4dE3aKQao8PrUn3Nb7d2DVucG", "recipient": "", "verification": "MANUAL_HASH"},
    {"code": "USDC_SOL", "name": "USDC", "network": "Solana", "address": "DDq3v8aj28dUw4mMcGUob94YgNQx9qn8XrNUnmQGpgPs", "recipient": "", "verification": "MANUAL_HASH"},
    {"code": "BTC", "name": "BTC", "network": "Bitcoin", "address": "14QTD6Eao9TMeuvStxjgrhyr9Qr4PSQ3rR", "recipient": "", "verification": "MANUAL_HASH"},
    {"code": "BTC_BEP20", "name": "BTC / BNB Smart Chain", "network": "BEP20 / BNB Smart Chain", "address": "0x37e801c682cc4fb65cd501ae450149c274b6ba6c", "recipient": "", "verification": "MANUAL_HASH"},
    {"code": "ETH", "name": "ETH", "network": "Ethereum", "address": "0x37e801c682cc4fb65cd501ae450149c274b6ba6c", "recipient": "", "verification": "MANUAL_HASH"},
    {"code": "SOL", "name": "SOL", "network": "Solana", "address": "DDq3v8aj28dUw4mMcGUob94YgNQx9qn8XrNUnmQGpgPs", "recipient": "", "verification": "MANUAL_HASH"},
    {"code": "BINANCE", "name": "Binance UID", "network": "Binance internal UID transfer", "address": "1035801756", "recipient": "", "verification": "MANUAL_PROOF"},
)


def utc_now():
    return datetime.now(UTC)


def utc_iso(value=None):
    if value is None:
        return utc_now().isoformat()
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("A UTC offset is required for timestamps.")
    return value.astimezone(UTC).isoformat()


def parse_utc(value):
    return datetime.fromisoformat(utc_iso(value))


def _integer(value, name, minimum=1, maximum=1000000):
    number = int(value)
    if number != float(value) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return number


def _money(value):
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid monetary amount.") from None
    if not result.is_finite() or result < 0 or result > 1000000000:
        raise ValueError("Amount must be finite and non-negative.")
    return result


def _timezone(name):
    aliases = {"EAT": "Africa/Kampala", "Africa-Kampala": "Africa/Kampala", "London": "Europe/London", "New York": "America/New_York"}
    name = aliases.get(str(name), str(name))
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Choose a valid IANA display timezone, such as UTC or Africa/Kampala.") from None
    return name


def migrate(con):
    """Idempotent schema extension, called by the existing store.connect."""
    additions = {
        "clients": {"archived_utc": "TEXT NOT NULL DEFAULT ''", "display_timezone": "TEXT NOT NULL DEFAULT 'UTC'", "max_mt5_accounts": "INTEGER NOT NULL DEFAULT 0"},
        "sessions": {"account_id": "INTEGER"},
        "subscriptions": {"max_mt5_accounts": "INTEGER NOT NULL DEFAULT 1", "access_kind": "TEXT NOT NULL DEFAULT 'TRIAL'"},
        "payment_requests": {"method": "TEXT NOT NULL DEFAULT ''", "proof": "TEXT NOT NULL DEFAULT ''", "transaction_hash": "TEXT NOT NULL DEFAULT ''", "duration_days": "INTEGER NOT NULL DEFAULT 30", "max_mt5_accounts": "INTEGER NOT NULL DEFAULT 1", "review_note": "TEXT NOT NULL DEFAULT ''", "approved_utc": "TEXT NOT NULL DEFAULT ''"},
    }
    for table, fields in additions.items():
        existing = {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
        for name, declaration in fields.items():
            if name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
    schema = """
    CREATE TABLE IF NOT EXISTS azt_plans(code TEXT PRIMARY KEY,name TEXT NOT NULL,amount REAL,currency TEXT NOT NULL,duration_days INTEGER NOT NULL,max_mt5_accounts INTEGER NOT NULL,trial_days INTEGER NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS client_mt5_accounts(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id INTEGER NOT NULL,login INTEGER NOT NULL,server TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ACTIVE',created_utc TEXT NOT NULL,UNIQUE(login,server));
    CREATE TABLE IF NOT EXISTS account_instruction_deliveries(instruction_id INTEGER NOT NULL,account_id INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING',ack_message TEXT NOT NULL DEFAULT '',acked_utc TEXT NOT NULL DEFAULT '',dispatched_utc TEXT NOT NULL DEFAULT '',PRIMARY KEY(instruction_id,account_id));
    CREATE TABLE IF NOT EXISTS azt_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,created_utc TEXT NOT NULL,read_utc TEXT NOT NULL DEFAULT '',event_key TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS azt_events(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,message TEXT NOT NULL,client_id INTEGER,created_utc TEXT NOT NULL,event_key TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS azt_distributor_trials(
        client_id INTEGER PRIMARY KEY,
        days INTEGER NOT NULL DEFAULT 30,
        created_utc TEXT NOT NULL,
        activated_utc TEXT NOT NULL DEFAULT '',
        expires_utc TEXT NOT NULL DEFAULT '',
        revoked_utc TEXT NOT NULL DEFAULT '',
        converted_utc TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(client_id) REFERENCES clients(id));
    CREATE TABLE IF NOT EXISTS referral_codes(client_id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS referral_links(client_id INTEGER PRIMARY KEY,referrer_id INTEGER NOT NULL,created_utc TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS referral_rewards(id INTEGER PRIMARY KEY AUTOINCREMENT,payment_id INTEGER NOT NULL UNIQUE,referrer_id INTEGER NOT NULL,client_id INTEGER NOT NULL,amount REAL NOT NULL,currency TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'PENDING',created_utc TEXT NOT NULL,paid_utc TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS promo_codes(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL UNIQUE,enabled INTEGER NOT NULL,plan_code TEXT NOT NULL,duration_days INTEGER NOT NULL,max_redemptions INTEGER NOT NULL,max_mt5_accounts INTEGER NOT NULL,expires_utc TEXT NOT NULL DEFAULT '',one_use_per_user INTEGER NOT NULL DEFAULT 1,created_utc TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS promo_redemptions(id INTEGER PRIMARY KEY AUTOINCREMENT,promo_id INTEGER NOT NULL,client_id INTEGER NOT NULL,created_utc TEXT NOT NULL,max_mt5_accounts INTEGER NOT NULL,expires_utc TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS azt_message_client ON azt_messages(client_id,id);
    CREATE INDEX IF NOT EXISTS azt_account_client ON client_mt5_accounts(client_id,status);
    """
    for statement in schema.split(";"):
        if statement.strip():
            con.execute(statement)
    delivery_columns = {row["name"] for row in con.execute("PRAGMA table_info(account_instruction_deliveries)")}
    if "dispatched_utc" not in delivery_columns:
        con.execute("ALTER TABLE account_instruction_deliveries ADD COLUMN dispatched_utc TEXT NOT NULL DEFAULT ''")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS azt_account_identity ON client_mt5_accounts(login,server COLLATE NOCASE)")
    if not con.execute("SELECT 1 FROM server_settings WHERE key='azt_accounts_backfilled'").fetchone():
        con.execute("INSERT OR IGNORE INTO client_mt5_accounts(client_id,login,server,status,created_utc) SELECT id,mt5_login,mt5_server,'ACTIVE',created_utc FROM clients WHERE archived_utc='' AND mt5_login>0 AND trim(mt5_server)<>'' ORDER BY id")
        con.execute("INSERT INTO server_settings(key,value) VALUES('azt_accounts_backfilled','1')")
    con.execute("INSERT OR IGNORE INTO azt_plans VALUES('STARTER','Starter',NULL,'USD',30,1,7,1)")
    defaults = {"azt_reminder_days": "[3,1,0]", "azt_referral_settings": '{"enabled":false,"mode":"PERCENT","value":0,"recurring":false,"currency":"USD"}'}
    for key, value in defaults.items():
        con.execute("INSERT OR IGNORE INTO server_settings(key,value) VALUES(?,?)", (key, value))


@contextmanager
def _db():
    from . import store
    con = store.connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _client_row(con, client_id, *, allow_archived=False):
    row = con.execute("SELECT * FROM clients WHERE id=?", (int(client_id),)).fetchone()
    if row is None or (row["archived_utc"] and not allow_archived):
        raise ValueError("Client not found or archived.")
    return row


def _event(con, kind, message, client_id=None, event_key=None):
    con.execute("INSERT OR IGNORE INTO azt_events(kind,message,client_id,created_utc,event_key) VALUES(?,?,?,?,?)", (kind, str(message)[:2000], client_id, utc_iso(), event_key))


def record_event(kind, message, client_id=None, event_key=None):
    with _db() as con:
        _event(con, kind, message, client_id, event_key)


def system_events(limit=100):
    with _db() as con:
        return [dict(row) for row in con.execute("SELECT * FROM azt_events ORDER BY id DESC LIMIT ?", (_integer(limit, "Limit", 1, 1000),))]


def plans():
    with _db() as con:
        return [dict(row) for row in con.execute("SELECT * FROM azt_plans ORDER BY code")]


def save_plan(code, *, name="", amount=None, currency="USD", duration_days=30, max_mt5_accounts=1, trial_days=7, enabled=True):
    code = str(code).strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{1,40}", code):
        raise ValueError("Use a plan code containing letters, numbers, underscores or hyphens.")
    currency = str(currency).strip().upper()
    if not re.fullmatch(r"[A-Z]{3,10}", currency):
        raise ValueError("Invalid currency code.")
    price = None if amount is None or str(amount).strip() == "" else float(_money(amount))
    duration_days = _integer(duration_days, "Duration", 1, 3660)
    max_mt5_accounts = _integer(max_mt5_accounts, "Account allowance", 1, 100)
    trial_days = _integer(trial_days, "Trial days", 1, 365)
    with _db() as con:
        con.execute("INSERT INTO azt_plans VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name,amount=excluded.amount,currency=excluded.currency,duration_days=excluded.duration_days,max_mt5_accounts=excluded.max_mt5_accounts,trial_days=excluded.trial_days,enabled=excluded.enabled", (code, str(name or code)[:80], price, currency, duration_days, max_mt5_accounts, trial_days, int(bool(enabled))))
    return next(plan for plan in plans() if plan["code"] == code)


def _ensure_subscription(con, client_id):
    _client_row(con, client_id)
    now = utc_iso()
    plan = con.execute("SELECT * FROM azt_plans WHERE code='STARTER'").fetchone()
    expiry = utc_iso(utc_now() + timedelta(days=int(plan["trial_days"])))
    con.execute("INSERT OR IGNORE INTO subscriptions(client_id,plan_code,status,starts_utc,expires_utc,auto_renew,updated_utc,max_mt5_accounts,access_kind) VALUES(?,'STARTER','TRIAL',?,?,0,?,?,'TRIAL')", (client_id, now, expiry, now, int(plan["max_mt5_accounts"])))
    # Legacy indefinite trials become a clearly recorded timed trial. Existing
    # explicit expiry dates and paid access are not shortened or rewritten.
    row = con.execute("SELECT * FROM subscriptions WHERE client_id=?", (client_id,)).fetchone()
    if row["status"] in {"TRIAL", "ACTIVE"} and not row["expires_utc"]:
        if row["status"] == "ACTIVE":
            selected = con.execute("SELECT duration_days FROM azt_plans WHERE code=?", (row["plan_code"],)).fetchone()
            expiry = utc_iso(utc_now() + timedelta(days=int(selected[0] if selected else 30)))
        con.execute("UPDATE subscriptions SET starts_utc=?,expires_utc=?,updated_utc=? WHERE client_id=?", (row["starts_utc"] or now, expiry, now, client_id))
        _event(con, "SUBSCRIPTION", "Legacy access without an expiry now has a configured expiry.", client_id, f"access-timed:{client_id}")
        row = con.execute("SELECT * FROM subscriptions WHERE client_id=?", (client_id,)).fetchone()
    return dict(row)


def _base_subscription_summary(con, client_id, now):
    client = _client_row(con, client_id)
    sub = _ensure_subscription(con, client_id)
    remaining = None
    effective = str(sub["status"]).upper()
    if sub["expires_utc"]:
        try:
            remaining = max(0, int((parse_utc(sub["expires_utc"]) - now).total_seconds()))
            if remaining <= 0:
                effective = "EXPIRED"
            elif effective in {"TRIAL", "ACTIVE"} and remaining <= 3 * 86400:
                effective = "EXPIRING SOON"
        except ValueError:
            effective = "INVALID_EXPIRY"
    if client["status"] != "ACTIVE":
        effective = str(client["status"])
    allowed = client["status"] == "ACTIVE" and sub["status"] in {"ACTIVE", "TRIAL", "EXPIRING SOON"} and effective not in {"EXPIRED", "INVALID_EXPIRY"}
    return {"subscription": sub, "allowed": allowed, "effective_status": effective,
             "remaining_seconds": remaining, "display_timezone": client["display_timezone"],
             "max_mt5_accounts": int(client["max_mt5_accounts"] or sub["max_mt5_accounts"] or 1),
             "reason": "OK" if allowed else "SUBSCRIPTION_" + effective.replace(" ", "_")}


def _subscription_summary(con, client_id, now=None):
    from .trial_licenses import apply_access

    current = now or utc_now()
    return apply_access(con, client_id, _base_subscription_summary(con, client_id, current), now=current)


def subscription_summary(client_id):
    with _db() as con:
        return _subscription_summary(con, client_id)


def _renew(con, client_id, days, plan_code=None, max_mt5_accounts=None, paid=True):
    sub = _ensure_subscription(con, client_id)
    now = utc_now()
    old_expiry = parse_utc(sub["expires_utc"]) if sub["expires_utc"] else now
    base = max(now, old_expiry) if sub["status"] in {"ACTIVE", "TRIAL", "EXPIRING SOON"} else now
    expires = utc_iso(base + timedelta(days=_integer(days, "Duration", 1, 3660)))
    accounts = _integer(max_mt5_accounts if max_mt5_accounts is not None else sub["max_mt5_accounts"], "MT5 account allowance", 1, 100)
    con.execute("UPDATE subscriptions SET plan_code=?,status=?,starts_utc=?,expires_utc=?,max_mt5_accounts=?,access_kind=?,updated_utc=? WHERE client_id=?", (plan_code or sub["plan_code"], "ACTIVE" if paid else "TRIAL", sub["starts_utc"] if old_expiry > now and sub["starts_utc"] else utc_iso(now), expires, accounts, "PAID" if paid else "PROMO", utc_iso(now), client_id))
    # Paid renewal restores an expired client, never an explicit pause/revoke.
    con.execute("UPDATE clients SET status='ACTIVE' WHERE id=? AND status='EXPIRED' AND archived_utc=''", (client_id,))
    _event(con, "SUBSCRIPTION", f"Access extended through {expires}.", client_id)
    return dict(con.execute("SELECT * FROM subscriptions WHERE client_id=?", (client_id,)).fetchone())


def renew_subscription(client_id, days, *, plan_code=None, max_mt5_accounts=None, paid=True):
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        result = _renew(con, client_id, days, plan_code, max_mt5_accounts, paid)
    return result


def edit_client(client_id, *, name=None, telegram_username=None, max_mt5_accounts=None, display_timezone=None):
    with _db() as con:
        _client_row(con, client_id)
        if name is not None:
            name = str(name).strip()
            if not name or len(name) > 100:
                raise ValueError("Client name is required (maximum 100 characters).")
            con.execute("UPDATE clients SET name=? WHERE id=?", (name, client_id))
        if telegram_username is not None:
            con.execute("UPDATE clients SET telegram_username=? WHERE id=?", (str(telegram_username).strip().lstrip("@")[:80], client_id))
        if display_timezone is not None:
            con.execute("UPDATE clients SET display_timezone=? WHERE id=?", (_timezone(display_timezone), client_id))
        if max_mt5_accounts is not None:
            limit = _integer(max_mt5_accounts, "Account allowance", 1, 100)
            count = con.execute("SELECT count(*) FROM client_mt5_accounts WHERE client_id=? AND status='ACTIVE'", (client_id,)).fetchone()[0]
            if count > limit:
                raise ValueError("Disable excess MT5 accounts before lowering this limit.")
            con.execute("UPDATE clients SET max_mt5_accounts=? WHERE id=?", (limit, client_id))
        return dict(con.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone())


def archive_client(client_id):
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        _client_row(con, client_id)
        con.execute("UPDATE clients SET archived_utc=?,status='REVOKED' WHERE id=?", (utc_iso(), client_id))
        con.execute("DELETE FROM sessions WHERE client_id=?", (client_id,))
        con.execute("UPDATE client_mt5_accounts SET status='DISABLED' WHERE client_id=?", (client_id,))
        con.execute("UPDATE hosted_accounts SET status='DISABLED',updated_utc=? WHERE client_id=?", (utc_iso(), client_id))
        _event(con, "CLIENT_ARCHIVED", "Client archived; trading access and sessions revoked; history retained.", client_id)


def list_accounts(client_id):
    with _db() as con:
        _client_row(con, client_id)
        return [dict(row) for row in con.execute("SELECT * FROM client_mt5_accounts WHERE client_id=? ORDER BY id", (client_id,))]


def set_account_limit(client_id, limit):
    return edit_client(client_id, max_mt5_accounts=limit)


def disable_account(client_id, account_id):
    with _db() as con:
        changed = con.execute("UPDATE client_mt5_accounts SET status='DISABLED' WHERE id=? AND client_id=?", (int(account_id), int(client_id))).rowcount
        con.execute("DELETE FROM sessions WHERE account_id=? AND client_id=?", (int(account_id), int(client_id)))
        if not changed:
            raise ValueError("MT5 account not found.")


def enable_account(client_id, account_id):
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        summary = _subscription_summary(con, client_id)
        account = con.execute("SELECT * FROM client_mt5_accounts WHERE id=? AND client_id=?", (int(account_id), int(client_id))).fetchone()
        if account is None:
            raise ValueError("MT5 account not found.")
        if account["status"] == "ACTIVE":
            return True
        count = con.execute("SELECT count(*) FROM client_mt5_accounts WHERE client_id=? AND status='ACTIVE'", (client_id,)).fetchone()[0]
        if count >= summary["max_mt5_accounts"]:
            raise ValueError("MT5 account limit reached.")
        con.execute("UPDATE client_mt5_accounts SET status='ACTIVE' WHERE id=? AND client_id=?", (account_id, client_id))
    return True


def authorize_account(client_id, login, server):
    login = _integer(login, "MT5 login", 1, 2**63 - 1)
    server = str(server).strip()
    if not server or len(server) > 100:
        raise ValueError("MT5 server is required.")
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        client = _client_row(con, client_id)
        summary = _subscription_summary(con, client_id)
        row = con.execute("SELECT * FROM client_mt5_accounts WHERE login=? AND server=? COLLATE NOCASE", (login, server)).fetchone()
        if row and row["client_id"] != client_id:
            raise ValueError("This MT5 account is already assigned to another client.")
        if row and row["status"] == "DISABLED":
            raise ValueError("This MT5 account has been disabled by Admin.")
        if row is None:
            # Preserve the existing primary binding while registering it into
            # the new account registry; it consumes an account slot too.
            if client["mt5_login"] is not None:
                con.execute("INSERT OR IGNORE INTO client_mt5_accounts(client_id,login,server,created_utc) VALUES(?,?,?,?)", (client_id, client["mt5_login"], client["mt5_server"], utc_iso()))
                row = con.execute("SELECT * FROM client_mt5_accounts WHERE login=? AND server=? COLLATE NOCASE", (login, server)).fetchone()
            if row is None:
                count = con.execute("SELECT count(*) FROM client_mt5_accounts WHERE client_id=? AND status='ACTIVE'", (client_id,)).fetchone()[0]
                if count >= summary["max_mt5_accounts"]:
                    raise ValueError("MT5 account limit reached. Ask Admin to increase the subscription allowance.")
                cur = con.execute("INSERT INTO client_mt5_accounts(client_id,login,server,created_utc) VALUES(?,?,?,?)", (client_id, login, server, utc_iso()))
                row = con.execute("SELECT * FROM client_mt5_accounts WHERE id=?", (cur.lastrowid,)).fetchone()
        if client["mt5_login"] is None:
            con.execute("UPDATE clients SET mt5_login=?,mt5_server=? WHERE id=?", (login, server, client_id))
        if row["client_id"] != client_id:
            raise ValueError("This MT5 account is already assigned to another client.")
        return dict(row)


def session_context(token):
    with _db() as con:
        row = con.execute("SELECT s.*,a.login,a.server,a.status AS account_status,c.archived_utc FROM sessions s JOIN clients c ON c.id=s.client_id LEFT JOIN client_mt5_accounts a ON a.id=s.account_id AND a.client_id=s.client_id WHERE s.token=? AND c.archived_utc=''", (str(token),)).fetchone()
        return dict(row) if row else None


def trade_access(token):
    context = session_context(token)
    if context is None:
        return {"allowed": False, "reason": "INVALID_SESSION"}
    summary = subscription_summary(context["client_id"])
    with _db() as con:
        client = _client_row(con, context["client_id"])
        if client["execution_mode"] != "CLIENT_PC":
            summary.update(allowed=False, reason="CLIENT_EXECUTION_MODE_HOSTED")
    if not context["account_id"] or context["account_status"] != "ACTIVE":
        summary.update(allowed=False, reason="MT5_ACCOUNT_NOT_AUTHORIZED")
    else:
        with _db() as con:
            position = con.execute("SELECT count(*) FROM client_mt5_accounts WHERE client_id=? AND status='ACTIVE' AND id<=?", (context["client_id"], context["account_id"])).fetchone()[0]
        if position > summary["max_mt5_accounts"]:
            summary.update(allowed=False, reason="MT5_ACCOUNT_LIMIT_EXCEEDED")
    summary["context"] = context
    return summary


def next_account_instruction(client_id, account_id, since):
    """Reserve before returning; a lost HTTP response is never re-dispatched.

    This durable account-scoped reservation protects the same MT5 account even
    when two separate PCs poll simultaneously. It has no lease or automatic
    expiry: an ambiguous delivery needs review, never an automatic order retry.
    """
    since = utc_iso(since)
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        if not con.execute("SELECT 1 FROM client_mt5_accounts WHERE id=? AND client_id=? AND status='ACTIVE'", (account_id, client_id)).fetchone():
            raise ValueError("MT5 account is not authorized.")
        # Serialize submission for this broker account across separate PCs.
        # Otherwise different simultaneous signals could both size against the
        # same pre-entry portfolio snapshot and exceed aggregate risk limits.
        if con.execute("SELECT 1 FROM account_instruction_deliveries WHERE account_id=? AND status='DISPATCHED' LIMIT 1", (account_id,)).fetchone():
            return None
        row = con.execute("SELECT i.* FROM instructions i LEFT JOIN account_instruction_deliveries d ON d.instruction_id=i.id AND d.account_id=? WHERE i.client_id=? AND i.created_utc>=? AND d.instruction_id IS NULL ORDER BY i.id LIMIT 1", (account_id, client_id, since)).fetchone()
        if row is None:
            return None
        con.execute("INSERT INTO account_instruction_deliveries(instruction_id,account_id,status,dispatched_utc) VALUES(?,?,'DISPATCHED',?)", (row["id"], account_id, utc_iso()))
        return dict(row)


def acknowledge_account_instruction(client_id, account_id, instruction_id, status, message, *, return_status=False):
    status = str(status).upper()
    if status not in {"EXECUTED", "REJECTED", "SKIPPED", "ERROR_REVIEW", "TEST_OK", "DUPLICATE"}:
        raise ValueError("Invalid instruction acknowledgment status.")
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        if not con.execute("SELECT 1 FROM client_mt5_accounts WHERE id=? AND client_id=? AND status='ACTIVE'", (account_id, client_id)).fetchone():
            return False
        row = con.execute("SELECT * FROM instructions WHERE id=? AND client_id=?", (int(instruction_id), int(client_id))).fetchone()
        if row is None:
            return False
        existing = con.execute("SELECT status,ack_message FROM account_instruction_deliveries WHERE instruction_id=? AND account_id=?", (instruction_id, account_id)).fetchone()
        if existing and existing["status"] not in {"DISPATCHED", "PENDING"}:
            # A late/conflicting ACK cannot reopen a finalized delivery. The
            # HTTP API acknowledges its receipt so a client cannot get stuck.
            if return_status:
                return "ALREADY_FINAL"
            return existing["status"] == status and existing["ack_message"] == str(message)[:1000]
        if existing:
            changed = con.execute("UPDATE account_instruction_deliveries SET status=?,ack_message=?,acked_utc=? WHERE instruction_id=? AND account_id=? AND status IN ('DISPATCHED','PENDING')", (status, str(message)[:1000], utc_iso(), instruction_id, account_id)).rowcount
        else:
            # Compatibility for a confirmed result from an older client that
            # received its instruction before this reservation schema upgrade.
            # This can only close an owned instruction/account; it never sends
            # an order or makes that instruction eligible for dispatch again.
            changed = con.execute("INSERT INTO account_instruction_deliveries(instruction_id,account_id,status,ack_message,acked_utc) VALUES(?,?,?,?,?)", (instruction_id, account_id, status, str(message)[:1000], utc_iso())).rowcount
        if changed:
            # Keep the legacy owner's instruction summary without suppressing
            # delivery to a different authorized account of this same client.
            con.execute("UPDATE instructions SET status=?,ack_message=?,acked_utc=? WHERE id=?", (status, str(message)[:1000], utc_iso(), instruction_id))
        return ("ACKNOWLEDGED" if changed else "NOT_FOUND") if return_status else bool(changed)


def instruction_deliveries(client_id):
    """Local owner review view; never exposed through a client Admin API."""
    with _db() as con:
        _client_row(con, client_id, allow_archived=True)
        return [dict(row) for row in con.execute("SELECT d.instruction_id,d.account_id,d.status,d.ack_message,d.acked_utc,d.dispatched_utc,i.signal_key,a.login,a.server FROM account_instruction_deliveries d JOIN instructions i ON i.id=d.instruction_id JOIN client_mt5_accounts a ON a.id=d.account_id AND a.client_id=i.client_id WHERE i.client_id=? ORDER BY (d.status='DISPATCHED') DESC,d.instruction_id DESC,d.account_id LIMIT 500", (int(client_id),))]


def resolve_delivery(client_id, account_id, instruction_id, note):
    """Owner-only reconciliation marker. Never resubmit or clear a claim.

    The operator must inspect the broker account before using this action. A
    final ERROR_REVIEW reservation remains durable while later fresh signals
    can proceed; the unresolved instruction itself is never offered again.
    """
    note = str(note).strip()
    if not note or len(note) > 2000:
        raise ValueError("Record a reconciliation note of 1-2000 characters.")
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        _client_row(con, client_id, allow_archived=True)
        row = con.execute("SELECT d.status FROM account_instruction_deliveries d JOIN instructions i ON i.id=d.instruction_id JOIN client_mt5_accounts a ON a.id=d.account_id AND a.client_id=i.client_id WHERE d.instruction_id=? AND d.account_id=? AND i.client_id=?", (int(instruction_id), int(account_id), int(client_id))).fetchone()
        if row is None:
            raise ValueError("Delivery not found for this client and MT5 account.")
        if row["status"] != "DISPATCHED":
            return False
        message = "OWNER_REVIEW: " + note
        now = utc_iso()
        con.execute("UPDATE account_instruction_deliveries SET status='ERROR_REVIEW',ack_message=?,acked_utc=? WHERE instruction_id=? AND account_id=? AND status='DISPATCHED'", (message, now, instruction_id, account_id))
        con.execute("UPDATE instructions SET status='ERROR_REVIEW',ack_message=?,acked_utc=? WHERE id=? AND client_id=?", (message[:1000], now, instruction_id, client_id))
        _event(con, "EXECUTION_REVIEW_RESOLVED", f"Delivery #{instruction_id} for MT5 account #{account_id} was manually reconciled. Its reservation is retained; no trade was resent. Note: {note}", client_id, f"delivery-resolved:{client_id}:{account_id}:{instruction_id}")
    return True


def preferences(client_id):
    with _db() as con:
        client = _client_row(con, client_id)
        return {"display_timezone": client["display_timezone"]}


def set_preferences(client_id, display_timezone="UTC"):
    edit_client(client_id, display_timezone=display_timezone)
    return preferences(client_id)


def _message(con, client_id, title, body, event_key=None):
    _client_row(con, client_id)
    title, body = str(title).strip(), str(body).strip()
    if not title or not body or len(title) > 160 or len(body) > 10000:
        raise ValueError("Message needs a title (up to 160 characters) and body (up to 10000).")
    cur = con.execute("INSERT OR IGNORE INTO azt_messages(client_id,title,body,created_utc,event_key) VALUES(?,?,?,?,?)", (client_id, title, body, utc_iso(), event_key))
    if cur.rowcount:
        return int(cur.lastrowid)
    row = con.execute("SELECT id FROM azt_messages WHERE event_key=? AND client_id=?", (event_key, client_id)).fetchone()
    return int(row["id"]) if row else None


def _telegram(client_id, title, body, event_key=None):
    try:
        from .client_notifications import enqueue_client_message
        from .store import DB_PATH
        return enqueue_client_message(client_id, f"AZT — {title}\n{body}", event_key=event_key, database=DB_PATH)
    except Exception:
        # In-app message is already committed and never depends on Telegram.
        return False


def send_message(client_id, title, body, *, also_telegram=False, event_key=None):
    with _db() as con:
        message_id = _message(con, client_id, title, body, event_key)
    queued = _telegram(client_id, title, body, event_key or f"message:{message_id}") if also_telegram else False
    return {"id": message_id, "telegram_queued": queued}


def broadcast_message(title, body, *, also_telegram=False):
    from .store import active_clients
    result = [send_message(c.id, title, body, also_telegram=also_telegram) for c in active_clients()]
    return {"sent": len(result), "telegram_queued": sum(bool(r["telegram_queued"]) for r in result)}


def messages(client_id, unread_only=False):
    with _db() as con:
        _client_row(con, client_id)
        return [dict(row) for row in con.execute("SELECT * FROM azt_messages WHERE client_id=? " + ("AND read_utc='' " if unread_only else "") + "ORDER BY id DESC LIMIT 500", (client_id,))]


def mark_message_read(client_id, message_id):
    with _db() as con:
        return bool(con.execute("UPDATE azt_messages SET read_utc=CASE WHEN read_utc='' THEN ? ELSE read_utc END WHERE id=? AND client_id=?", (utc_iso(), int(message_id), int(client_id))).rowcount)


def payment_methods():
    return [dict(item) for item in PAYMENT_METHODS]


def _validate_proof(proof):
    proof = str(proof or "").strip()
    if proof.startswith("data:"):
        header, separator, encoded = proof.partition(",")
        if header not in {"data:image/png;base64", "data:image/jpeg;base64"} or not separator:
            raise ValueError("Proof must be a PNG or JPEG image.")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            raise ValueError("Invalid proof image encoding.") from None
        if len(decoded) > 5 * 1024 * 1024 or not (decoded.startswith(b"\x89PNG\r\n\x1a\n") or decoded.startswith(b"\xff\xd8\xff")):
            raise ValueError("Proof must be a PNG/JPEG image of at most 5 MB.")
        try:
            from PIL import Image
            with Image.open(io.BytesIO(decoded)) as image:
                if image.width * image.height > 20000000:
                    raise ValueError("Proof screenshot dimensions are too large.")
                image.verify()
        except Exception:
            raise ValueError("Payment proof is not a valid bounded PNG/JPEG image.") from None
    elif len(proof) > 4000:
        raise ValueError("Payment proof note is too long.")
    return proof


def submit_payment(client_id, plan_code, method, *, proof="", transaction_hash=""):
    method = str(method).strip().upper()
    chosen = next((m for m in PAYMENT_METHODS if m["code"] == method), None)
    if chosen is None:
        raise ValueError("Choose a supported payment method.")
    proof = _validate_proof(proof)
    transaction_hash = str(transaction_hash or "").strip()
    if chosen["verification"] == "MANUAL_HASH" and not re.fullmatch(r"[A-Za-z0-9]{32,160}", transaction_hash):
        raise ValueError("Provide the transaction hash for the exact network shown.")
    if chosen["verification"] == "MANUAL_PROOF" and not proof.startswith("data:image/"):
        raise ValueError("Attach a PNG/JPEG payment proof screenshot for manual verification.")
    if re.fullmatch(r"(?:0x)?[0-9A-Fa-f]{64}", transaction_hash):
        transaction_hash = transaction_hash.lower().removeprefix("0x")
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        _client_row(con, client_id)
        plan = con.execute("SELECT * FROM azt_plans WHERE code=? AND enabled=1", (str(plan_code).strip().upper(),)).fetchone()
        if plan is None or plan["amount"] is None or _money(plan["amount"]) <= 0:
            raise ValueError("This plan is not priced yet. Ask Admin to configure its subscription price.")
        if transaction_hash and con.execute("SELECT 1 FROM payment_requests WHERE transaction_hash=? AND status IN ('PENDING','APPROVED')", (transaction_hash,)).fetchone():
            raise ValueError("This transaction has already been submitted.")
        now = utc_iso()
        cur = con.execute("INSERT INTO payment_requests(client_id,kind,plan_code,amount,currency,provider,provider_reference,status,created_utc,updated_utc,method,proof,transaction_hash,duration_days,max_mt5_accounts) VALUES(?,'RENEWAL',?,?,?,'MANUAL',?,'PENDING',?,?,?,?,?,?,?)", (client_id, plan["code"], float(_money(plan["amount"])), plan["currency"], transaction_hash, now, now, method, proof, transaction_hash, plan["duration_days"], plan["max_mt5_accounts"]))
        payment_id = int(cur.lastrowid)
        _event(con, "PAYMENT_SUBMITTED", f"Payment #{payment_id} awaits manual {method} verification.", client_id)
        _message(con, client_id, "Payment pending verification", f"Payment #{payment_id} is pending manual review. No automatic blockchain verification is active.", f"payment-submitted:{payment_id}")
        return dict(con.execute("SELECT * FROM payment_requests WHERE id=?", (payment_id,)).fetchone())


def list_payments(client_id=None, status=None):
    clauses, args = [], []
    if client_id is not None:
        clauses.append("p.client_id=?")
        args.append(int(client_id))
    if status:
        clauses.append("p.status=?")
        args.append(str(status).upper())
    with _db() as con:
        rows = con.execute("SELECT p.*,c.name AS client_name FROM payment_requests p JOIN clients c ON c.id=p.client_id" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY p.id DESC LIMIT 500", args).fetchall()
        return [dict(row) for row in rows]


def _referral_settings(con):
    return json.loads(con.execute("SELECT value FROM server_settings WHERE key='azt_referral_settings'").fetchone()[0])


def referral_settings():
    with _db() as con:
        return _referral_settings(con)


def set_referral_settings(*, enabled=False, mode="PERCENT", value=0, recurring=False, currency="USD"):
    mode = str(mode).upper()
    if mode not in {"PERCENT", "FIXED"}:
        raise ValueError("Referral mode must be PERCENT or FIXED.")
    value = _money(value)
    if mode == "PERCENT" and value > 100:
        raise ValueError("Referral percentage cannot exceed 100.")
    currency = str(currency).upper().strip()
    if not re.fullmatch(r"[A-Z]{3,10}", currency):
        raise ValueError("Invalid reward currency.")
    settings = {"enabled": bool(enabled), "mode": mode, "value": float(value), "recurring": bool(recurring), "currency": currency}
    with _db() as con:
        con.execute("UPDATE server_settings SET value=? WHERE key='azt_referral_settings'", (json.dumps(settings),))
    return settings


def _reward(con, payment):
    settings = _referral_settings(con)
    if not settings["enabled"] or _money(settings["value"]) <= 0:
        return
    link = con.execute("SELECT * FROM referral_links WHERE client_id=?", (payment["client_id"],)).fetchone()
    if not link:
        return
    referrer = con.execute("SELECT * FROM clients WHERE id=? AND archived_utc=''", (link["referrer_id"],)).fetchone()
    if not referrer:
        return
    previous = con.execute("SELECT 1 FROM payment_requests WHERE client_id=? AND status='APPROVED' AND id<>?", (payment["client_id"], payment["id"])).fetchone()
    if previous and not settings["recurring"]:
        return
    if settings["mode"] == "FIXED" and settings["currency"] != payment["currency"]:
        return  # Never invent an exchange rate for a fixed reward.
    amount = (_money(payment["amount"]) * _money(settings["value"]) / 100).quantize(Decimal(".01")) if settings["mode"] == "PERCENT" else _money(settings["value"])
    # A reward cannot exceed the qualifying subscription revenue.
    amount = min(amount, _money(payment["amount"]))
    con.execute("INSERT OR IGNORE INTO referral_rewards(payment_id,referrer_id,client_id,amount,currency,created_utc) VALUES(?,?,?,?,?,?)", (payment["id"], link["referrer_id"], payment["client_id"], float(amount), payment["currency"], utc_iso()))


def review_payment(payment_id, approve, *, note=""):
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        payment = con.execute("SELECT * FROM payment_requests WHERE id=?", (int(payment_id),)).fetchone()
        if payment is None:
            raise ValueError("Payment not found.")
        desired = "APPROVED" if approve else "REJECTED"
        if payment["status"] == desired:
            return dict(payment)  # An approval retry never extends access twice.
        if payment["status"] != "PENDING":
            raise ValueError("Only a pending payment can be reviewed.")
        _client_row(con, payment["client_id"])
        if approve:
            if payment["provider"] != "MANUAL" or _money(payment["amount"]) <= 0:
                raise ValueError("Legacy/unpriced checkout requests cannot activate a subscription.")
            _renew(con, payment["client_id"], payment["duration_days"], payment["plan_code"], payment["max_mt5_accounts"], True)
        now = utc_iso()
        con.execute("UPDATE payment_requests SET status=?,review_note=?,updated_utc=?,approved_utc=? WHERE id=?", (desired, str(note)[:2000], now, now if approve else "", payment_id))
        if approve:
            _reward(con, dict(payment))
        _message(con, payment["client_id"], "Payment " + desired.lower(), f"Payment #{payment_id} was {desired.lower()}. " + str(note)[:1000], f"payment-reviewed:{payment_id}")
        _event(con, "PAYMENT_" + desired, f"Payment #{payment_id} {desired.lower()} after manual review.", payment["client_id"])
        result = dict(con.execute("SELECT * FROM payment_requests WHERE id=?", (payment_id,)).fetchone())
    return result


def link_referral(client_id, code):
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        _client_row(con, client_id)
        referrer = con.execute("SELECT r.* FROM referral_codes r JOIN clients c ON c.id=r.client_id WHERE r.code=? AND c.archived_utc=''", (str(code).strip().upper(),)).fetchone()
        if not referrer or referrer["client_id"] == client_id:
            raise ValueError("Invalid referral code or self-referral.")
        if con.execute("SELECT 1 FROM payment_requests WHERE client_id=? AND status='APPROVED'", (client_id,)).fetchone():
            raise ValueError("A referral must be linked before the first paid subscription approval.")
        existing = con.execute("SELECT * FROM referral_links WHERE client_id=?", (client_id,)).fetchone()
        if existing:
            if existing["referrer_id"] == referrer["client_id"]:
                return dict(existing)
            raise ValueError("A referring client is already assigned.")
        # Disallow referral cycles, even though rewards are single-level.
        ancestor, visited = referrer["client_id"], {client_id}
        while ancestor:
            if ancestor in visited:
                raise ValueError("Referral cycles are not allowed.")
            visited.add(ancestor)
            row = con.execute("SELECT referrer_id FROM referral_links WHERE client_id=?", (ancestor,)).fetchone()
            ancestor = row[0] if row else None
        con.execute("INSERT INTO referral_links VALUES(?,?,?)", (client_id, referrer["client_id"], utc_iso()))
        return {"client_id": client_id, "referrer_id": referrer["client_id"]}


def referral_summary(client_id):
    with _db() as con:
        _client_row(con, client_id)
        con.execute("INSERT OR IGNORE INTO referral_codes(client_id,code) VALUES(?,?)", (client_id, "AZT-" + secrets.token_hex(5).upper()))
        code = con.execute("SELECT code FROM referral_codes WHERE client_id=?", (client_id,)).fetchone()[0]
        linked = [dict(row) for row in con.execute("SELECT l.client_id,c.name,c.status,l.created_utc FROM referral_links l JOIN clients c ON c.id=l.client_id WHERE l.referrer_id=?", (client_id,))]
        rewards = [dict(row) for row in con.execute("SELECT * FROM referral_rewards WHERE referrer_id=? ORDER BY id DESC", (client_id,))]
        settings = _referral_settings(con)
    active = sum(1 for row in linked if row["status"] == "ACTIVE" and subscription_summary(row["client_id"])["allowed"])
    totals = {}
    paid = {}
    pending = {}
    for reward in rewards:
        reward["status"] = reward["state"]
        totals[reward["currency"]] = round(totals.get(reward["currency"], 0) + reward["amount"], 2)
        target = pending if reward["state"] == "PENDING" else paid
        target[reward["currency"]] = round(target.get(reward["currency"], 0) + reward["amount"], 2)
    policy = "Referral rewards are not enabled yet; no commission percentage is assumed." if not settings["enabled"] else "Rewards follow the configured policy and qualifying approved subscription payments; payouts are manually recorded."
    return {"code": code, "link": "/ref/" + code, "number_referred": len(linked), "active_referrals": active, "referred": linked, "rewards_earned": totals, "paid_rewards": paid, "pending_rewards": pending, "reward_history": rewards, "settings": settings, "policy_message": policy}


def mark_reward_paid(reward_id):
    with _db() as con:
        return bool(con.execute("UPDATE referral_rewards SET state='PAID',paid_utc=? WHERE id=? AND state='PENDING'", (utc_iso(), int(reward_id))).rowcount)


def save_promo(code, *, plan_code="STARTER", duration_days=30, max_redemptions=20, max_mt5_accounts=1, expires_utc="", enabled=True, one_use_per_user=True):
    code = str(code).strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{3,60}", code):
        raise ValueError("Promo code must be 3-60 letters, digits, underscores or hyphens.")
    duration = _integer(duration_days, "Access days", 1, 3660)
    maximum = _integer(max_redemptions, "Maximum redemptions", 1, 1000000)
    allowance = _integer(max_mt5_accounts, "MT5 account allowance", 1, 100)
    expiry = utc_iso(expires_utc) if expires_utc else ""
    with _db() as con:
        if not con.execute("SELECT 1 FROM azt_plans WHERE code=?", (str(plan_code).upper(),)).fetchone():
            raise ValueError("Configure the plan first.")
        old = con.execute("SELECT * FROM promo_codes WHERE code=?", (code,)).fetchone()
        if old and con.execute("SELECT count(*) FROM promo_redemptions WHERE promo_id=?", (old["id"],)).fetchone()[0] > maximum:
            raise ValueError("Maximum redemptions cannot be below existing usage.")
        con.execute("INSERT INTO promo_codes(code,enabled,plan_code,duration_days,max_redemptions,max_mt5_accounts,expires_utc,one_use_per_user,created_utc) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET enabled=excluded.enabled,plan_code=excluded.plan_code,duration_days=excluded.duration_days,max_redemptions=excluded.max_redemptions,max_mt5_accounts=excluded.max_mt5_accounts,expires_utc=excluded.expires_utc,one_use_per_user=excluded.one_use_per_user", (code, int(bool(enabled)), str(plan_code).upper(), duration, maximum, allowance, expiry, int(bool(one_use_per_user)), utc_iso()))
    return next(row for row in promos() if row["code"] == code)


def promos():
    with _db() as con:
        rows = [dict(row) for row in con.execute("SELECT p.*,count(r.id) AS usage_count FROM promo_codes p LEFT JOIN promo_redemptions r ON r.promo_id=p.id GROUP BY p.id ORDER BY p.id DESC")]
    for row in rows:
        row["remaining_uses"] = max(0, row["max_redemptions"] - row["usage_count"])
    return rows


def redeem_promo(client_id, code):
    with _db() as con:
        con.execute("BEGIN IMMEDIATE")
        _client_row(con, client_id)
        promo = con.execute("SELECT * FROM promo_codes WHERE code=?", (str(code).upper().strip(),)).fetchone()
        if promo is None or not promo["enabled"]:
            raise ValueError("Promo code is unavailable.")
        if promo["expires_utc"] and parse_utc(promo["expires_utc"]) <= utc_now():
            raise ValueError("Promo code has expired.")
        used = con.execute("SELECT count(*) FROM promo_redemptions WHERE promo_id=?", (promo["id"],)).fetchone()[0]
        if used >= promo["max_redemptions"]:
            raise ValueError("Promo code redemption limit reached.")
        previous = con.execute("SELECT * FROM promo_redemptions WHERE promo_id=? AND client_id=?", (promo["id"], client_id)).fetchone()
        if previous and promo["one_use_per_user"]:
            raise ValueError("This client has already redeemed that promo code.")
        current = _base_subscription_summary(con, client_id, utc_now())
        # Repeat redemptions may extend time only when explicitly configured;
        # they never multiply the granted account allowance.
        allowance = max(current["subscription"]["max_mt5_accounts"], promo["max_mt5_accounts"]) if current["allowed"] else promo["max_mt5_accounts"]
        existing_paid = current["allowed"] and current["subscription"].get("access_kind") == "PAID"
        grant_plan = current["subscription"]["plan_code"] if existing_paid else promo["plan_code"]
        sub = _renew(con, client_id, promo["duration_days"], grant_plan, allowance, existing_paid)
        con.execute("INSERT INTO promo_redemptions(promo_id,client_id,created_utc,max_mt5_accounts,expires_utc) VALUES(?,?,?,?,?)", (promo["id"], client_id, utc_iso(), promo["max_mt5_accounts"], sub["expires_utc"]))
        _message(con, client_id, "Promo access granted", f"{promo['code']} granted {promo['duration_days']} days with up to {promo['max_mt5_accounts']} MT5 accounts.")
    return subscription_summary(client_id)


def promo_redemptions(code):
    with _db() as con:
        return [dict(row) for row in con.execute("SELECT r.*,c.name AS client_name,(SELECT count(*) FROM client_mt5_accounts a WHERE a.client_id=r.client_id AND a.status='ACTIVE') AS account_count FROM promo_redemptions r JOIN promo_codes p ON p.id=r.promo_id JOIN clients c ON c.id=r.client_id WHERE p.code=? ORDER BY r.id DESC", (str(code).upper(),))]


def reminder_days():
    with _db() as con:
        return json.loads(con.execute("SELECT value FROM server_settings WHERE key='azt_reminder_days'").fetchone()[0])


def set_reminder_days(days):
    values = sorted({_integer(d, "Reminder day", 0, 365) for d in days}, reverse=True)
    with _db() as con:
        con.execute("UPDATE server_settings SET value=? WHERE key='azt_reminder_days'", (json.dumps(values),))
    return values


def maintenance_tick():
    """Idempotent in-app reminders; expiry enforcement also runs per request."""
    queued = []
    owner_alerts = []
    now = utc_now()
    with _db() as con:
        clients = [dict(row) for row in con.execute("SELECT * FROM clients WHERE archived_utc='' AND status NOT IN ('REVOKED','PAUSED')")]
        timings = json.loads(con.execute("SELECT value FROM server_settings WHERE key='azt_reminder_days'").fetchone()[0])
        try:
            from .workspace_settings import load_settings
            timings = sorted({_integer(day, "Reminder day", 0, 365) for day in load_settings().get("reminder_days", timings)}, reverse=True)
        except (OSError, ValueError, ImportError):
            pass
        for client in clients:
            access = _subscription_summary(con, client["id"], now=now)
            if access["effective_status"] == "PAYMENT_REQUIRED":
                continue
            sub = access["subscription"]
            distributor_trial = access.get("distributor_trial", False)
            if not sub["expires_utc"]:
                continue
            try:
                remaining = (parse_utc(sub["expires_utc"]) - now).total_seconds()
            except ValueError:
                continue
            if not distributor_trial and remaining <= 0 and sub["status"] not in {"EXPIRED", "CANCELLED", "REVOKED"}:
                con.execute("UPDATE subscriptions SET status='EXPIRED',updated_utc=? WHERE client_id=?", (utc_iso(), client["id"]))
                _event(con, "SUBSCRIPTION_EXPIRED", "Subscription expired; new entries blocked. Existing positions remain at the broker.", client["id"], f"expiry:{client['id']}:{sub['expires_utc']}")
            if sub["status"] not in {"ACTIVE", "TRIAL", "EXPIRED", "EXPIRING SOON"}:
                continue
            for days in timings:
                # Only the nearest reached interval is sent after downtime; do
                # not flood a client with all historical reminder thresholds.
                lower = max([d for d in timings if d < days], default=0)
                applicable = remaining <= 0 if days == 0 else lower * 86400 < remaining <= days * 86400
                if not applicable:
                    continue
                key = f"subscription-reminder:{client['id']}:{sub['expires_utc']}:{days}"
                if con.execute("SELECT 1 FROM azt_messages WHERE event_key=?", (key,)).fetchone():
                    continue
                displayed_expiry = parse_utc(sub["expires_utc"]).astimezone(ZoneInfo(client["display_timezone"])).isoformat()
                if distributor_trial:
                    title = "30-day trial expired" if days == 0 else "30-day trial expiring soon"
                    body = f"Your distributor trial expires at {displayed_expiry}. Contact Admin to arrange paid access."
                else:
                    title = "Subscription expired" if days == 0 else "Subscription expiring soon"
                    body = f"Your {sub['plan_code']} access expires at {displayed_expiry} ({client['display_timezone']}). " + ("New automated entries are blocked until renewal approval." if days == 0 else "Renew to keep automated trading available.")
                _message(con, client["id"], title, body, key)
                queued.append((client["id"], title, body, key))
        held = con.execute("SELECT d.instruction_id,d.account_id,d.dispatched_utc,i.client_id,c.name,c.archived_utc,a.login,a.server FROM account_instruction_deliveries d JOIN instructions i ON i.id=d.instruction_id JOIN clients c ON c.id=i.client_id JOIN client_mt5_accounts a ON a.id=d.account_id AND a.client_id=i.client_id WHERE d.status='DISPATCHED'").fetchall()
        for delivery in held:
            try:
                overdue = (now - parse_utc(delivery["dispatched_utc"])).total_seconds() >= 60
            except (TypeError, ValueError):
                overdue = True  # Unknown delivery time also requires review.
            key = f"delivery-review:{delivery['client_id']}:{delivery['account_id']}:{delivery['instruction_id']}"
            if not overdue or con.execute("SELECT 1 FROM azt_events WHERE event_key=?", (key,)).fetchone():
                continue
            body = f"Execution delivery #{delivery['instruction_id']} for {delivery['server']}|{delivery['login']} has no confirmed result. New automated entries for this account are held until the result is acknowledged or Admin reviews the broker account. The instruction will not be resent automatically."
            _event(con, "EXECUTION_REVIEW_REQUIRED", body, delivery["client_id"], key)
            if not delivery["archived_utc"]:
                _message(con, delivery["client_id"], "Execution needs review", body, key)
            owner_alerts.append((key, f"AZT • Execution needs review\nClient: {delivery['name']}\n{body}"))
    for client_id, title, body, key in queued:
        _telegram(client_id, title, body, key)
    for key, text in owner_alerts:
        try:
            from .telegram_notifications import enqueue_owner_event
            from .store import DB_PATH
            enqueue_owner_event(key, text, database=DB_PATH)
        except Exception:
            pass  # The local owner/client alerts are already committed.
    return {"reminders": len(queued), "execution_reviews": len(owner_alerts), "clients_checked": len(clients)}


def overview(client_id):
    from .store import client_by_id, news_lock_enabled
    client = client_by_id(client_id)
    summary = subscription_summary(client_id)
    return {"display_name": client.name, "status": client.status, "subscription": summary["subscription"], "subscription_status": summary["effective_status"], "allowed": summary["allowed"], "remaining_seconds": summary["remaining_seconds"], "max_mt5_accounts": summary["max_mt5_accounts"], "display_timezone": summary["display_timezone"], "accounts": list_accounts(client_id), "unread_messages": len(messages(client_id, True)), "news_lock": news_lock_enabled()}
