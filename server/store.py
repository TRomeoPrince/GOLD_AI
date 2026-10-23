from __future__ import annotations

import os
import secrets
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .credential_vault import encrypt_secret


def _resolve_db_path() -> Path:
    override = os.getenv("GOLD_AI_DB_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        candidates = [
            exe.parent.parent / "server" / "gold_ai_server.db",
            Path.cwd() / "server" / "gold_ai_server.db",
            Path.home() / "Desktop" / "Bots" / "Forex" / "AMD1" / "server" / "gold_ai_server.db",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

        fallback_dir = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "GOLD_AI" / "server"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir / "gold_ai_server.db"

    return Path(__file__).resolve().parent / "gold_ai_server.db"


DB_PATH = _resolve_db_path()


@dataclass
class ClientRecord:
    id: int
    name: str
    status: str
    pairing_code: str
    mt5_login: Optional[int]
    mt5_server: str
    telegram_username: str
    telegram_chat_id: Optional[int]
    created_utc: str
    risk_per_trade_pct: float = 0.9
    max_open_risk_pct: float = 40.0
    max_daily_loss_pct: float = 5.0
    risk_per_trade_enabled: int = 1
    max_open_risk_enabled: int = 1
    max_daily_loss_enabled: int = 1
    daily_profit_target_enabled: int = 0
    daily_profit_target_pct: float = 3.0
    execution_mode: str = "CLIENT_PC"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            pairing_code TEXT NOT NULL UNIQUE,
            mt5_login INTEGER,
            mt5_server TEXT NOT NULL DEFAULT '',
            telegram_username TEXT NOT NULL DEFAULT '',
            telegram_chat_id INTEGER,
            created_utc TEXT NOT NULL,
            risk_per_trade_pct REAL NOT NULL DEFAULT 0.9,
            max_open_risk_pct REAL NOT NULL DEFAULT 40.0,
            max_daily_loss_pct REAL NOT NULL DEFAULT 5.0,
            risk_per_trade_enabled INTEGER NOT NULL DEFAULT 1,
            max_open_risk_enabled INTEGER NOT NULL DEFAULT 1,
            max_daily_loss_enabled INTEGER NOT NULL DEFAULT 1,
            daily_profit_target_enabled INTEGER NOT NULL DEFAULT 0,
            daily_profit_target_pct REAL NOT NULL DEFAULT 3.0,
            execution_mode TEXT NOT NULL DEFAULT 'CLIENT_PC'
        )
        """
    )
    cols = {row["name"] for row in con.execute("PRAGMA table_info(clients)").fetchall()}
    migrations = {
        "telegram_chat_id": "ALTER TABLE clients ADD COLUMN telegram_chat_id INTEGER",
        "risk_per_trade_pct": "ALTER TABLE clients ADD COLUMN risk_per_trade_pct REAL NOT NULL DEFAULT 0.9",
        "max_open_risk_pct": "ALTER TABLE clients ADD COLUMN max_open_risk_pct REAL NOT NULL DEFAULT 40.0",
        "max_daily_loss_pct": "ALTER TABLE clients ADD COLUMN max_daily_loss_pct REAL NOT NULL DEFAULT 5.0",
        "risk_per_trade_enabled": "ALTER TABLE clients ADD COLUMN risk_per_trade_enabled INTEGER NOT NULL DEFAULT 1",
        "max_open_risk_enabled": "ALTER TABLE clients ADD COLUMN max_open_risk_enabled INTEGER NOT NULL DEFAULT 1",
        "max_daily_loss_enabled": "ALTER TABLE clients ADD COLUMN max_daily_loss_enabled INTEGER NOT NULL DEFAULT 1",
        "daily_profit_target_enabled": "ALTER TABLE clients ADD COLUMN daily_profit_target_enabled INTEGER NOT NULL DEFAULT 0",
        "daily_profit_target_pct": "ALTER TABLE clients ADD COLUMN daily_profit_target_pct REAL NOT NULL DEFAULT 3.0",
        "execution_mode": "ALTER TABLE clients ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'CLIENT_PC'",
    }
    for name, sql in migrations.items():
        if name not in cols:
            con.execute(sql)

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            client_id INTEGER NOT NULL,
            created_utc TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS instructions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            signal_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            ack_message TEXT NOT NULL DEFAULT '',
            created_utc TEXT NOT NULL,
            acked_utc TEXT NOT NULL DEFAULT '',
            UNIQUE(client_id, signal_key),
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS hosted_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL UNIQUE,
            mt5_login INTEGER NOT NULL,
            mt5_server TEXT NOT NULL,
            password_ciphertext TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            terminal_path TEXT NOT NULL DEFAULT '',
            worker_pid INTEGER,
            last_error TEXT NOT NULL DEFAULT '',
            last_seen_utc TEXT NOT NULL DEFAULT '',
            account_balance REAL,
            account_equity REAL,
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )
    hosted_cols = {
        row["name"] for row in con.execute("PRAGMA table_info(hosted_accounts)").fetchall()
    }
    hosted_migrations = {
        "terminal_path": "ALTER TABLE hosted_accounts ADD COLUMN terminal_path TEXT NOT NULL DEFAULT ''",
        "worker_pid": "ALTER TABLE hosted_accounts ADD COLUMN worker_pid INTEGER",
        "last_error": "ALTER TABLE hosted_accounts ADD COLUMN last_error TEXT NOT NULL DEFAULT ''",
        "last_seen_utc": "ALTER TABLE hosted_accounts ADD COLUMN last_seen_utc TEXT NOT NULL DEFAULT ''",
        "account_balance": "ALTER TABLE hosted_accounts ADD COLUMN account_balance REAL",
        "account_equity": "ALTER TABLE hosted_accounts ADD COLUMN account_equity REAL",
    }
    for name, sql in hosted_migrations.items():
        if name not in hosted_cols:
            con.execute(sql)

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            client_id INTEGER PRIMARY KEY,
            plan_code TEXT NOT NULL DEFAULT 'STARTER',
            status TEXT NOT NULL DEFAULT 'TRIAL',
            starts_utc TEXT NOT NULL DEFAULT '',
            expires_utc TEXT NOT NULL DEFAULT '',
            auto_renew INTEGER NOT NULL DEFAULT 0,
            updated_utc TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT 'RENEWAL',
            plan_code TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'USD',
            provider TEXT NOT NULL DEFAULT 'UNSET',
            provider_reference TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'PENDING',
            checkout_url TEXT NOT NULL DEFAULT '',
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS server_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    defaults = {
        "news_lock": "0",
        "global_risk_per_trade_enabled": "1",
        "global_risk_per_trade_pct": "2.0",
        "global_max_open_risk_enabled": "1",
        "global_max_open_risk_pct": "40.0",
        "global_max_daily_loss_enabled": "1",
        "global_max_daily_loss_pct": "10.0",
        "global_daily_profit_target_enabled": "0",
        "global_daily_profit_target_pct": "3.0",
    }
    for key, value in defaults.items():
        con.execute(
            "INSERT OR IGNORE INTO server_settings(key,value) VALUES(?,?)",
            (key, value),
        )
    con.commit()
    return con


def _client(row) -> ClientRecord | None:
    return ClientRecord(**dict(row)) if row else None


def create_client(name: str) -> tuple[ClientRecord, str]:
    code = secrets.token_urlsafe(8)
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        cur = con.execute(
            "INSERT INTO clients(name,status,pairing_code,created_utc) VALUES(?,?,?,?)",
            (name.strip(), "ACTIVE", code, now),
        )
        row = con.execute("SELECT * FROM clients WHERE id=?", (cur.lastrowid,)).fetchone()
    return _client(row), code


def list_clients() -> list[ClientRecord]:
    with connect() as con:
        rows = con.execute("SELECT * FROM clients ORDER BY id").fetchall()
    return [_client(row) for row in rows]


def set_status(name: str, status: str) -> None:
    status = status.upper()
    if status not in {"ACTIVE", "PAUSED", "REVOKED", "EXPIRED"}:
        raise ValueError("Status must be ACTIVE, PAUSED, REVOKED or EXPIRED.")
    with connect() as con:
        cur = con.execute("UPDATE clients SET status=? WHERE name=?", (status, name))
        if cur.rowcount == 0:
            raise ValueError(f"Unknown client: {name}")


def set_client_risk(
    name: str,
    risk_per_trade_pct: float,
    max_open_risk_pct: float,
    max_daily_loss_pct: float,
    *,
    risk_per_trade_enabled: bool = True,
    max_open_risk_enabled: bool = True,
    max_daily_loss_enabled: bool = True,
    daily_profit_target_enabled: bool = False,
    daily_profit_target_pct: float = 3.0,
) -> ClientRecord:
    risk_per_trade_pct = float(risk_per_trade_pct)
    max_open_risk_pct = float(max_open_risk_pct)
    max_daily_loss_pct = float(max_daily_loss_pct)
    daily_profit_target_pct = float(daily_profit_target_pct)

    if not 0.1 <= risk_per_trade_pct <= 2.0:
        raise ValueError("Risk per trade must be between 0.1% and 2.0%.")
    if not 5.0 <= max_open_risk_pct <= 40.0:
        raise ValueError("Max overall open risk must be between 5% and 40%.")
    if not 2.0 <= max_daily_loss_pct <= 10.0:
        raise ValueError("Max daily loss must be between 2% and 10%.")
    if daily_profit_target_pct <= 0:
        raise ValueError("Daily profit target must be greater than 0%.")

    with connect() as con:
        cur = con.execute(
            """
            UPDATE clients
            SET risk_per_trade_pct=?, max_open_risk_pct=?, max_daily_loss_pct=?,
                risk_per_trade_enabled=?, max_open_risk_enabled=?,
                max_daily_loss_enabled=?, daily_profit_target_enabled=?,
                daily_profit_target_pct=?
            WHERE name=?
            """,
            (
                risk_per_trade_pct,
                max_open_risk_pct,
                max_daily_loss_pct,
                1 if risk_per_trade_enabled else 0,
                1 if max_open_risk_enabled else 0,
                1 if max_daily_loss_enabled else 0,
                1 if daily_profit_target_enabled else 0,
                daily_profit_target_pct,
                name.strip(),
            ),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown client: {name}")
        row = con.execute("SELECT * FROM clients WHERE name=?", (name.strip(),)).fetchone()
    return _client(row)


def get_global_risk_policy() -> dict:
    with connect() as con:
        rows = con.execute(
            "SELECT key,value FROM server_settings WHERE key LIKE 'global_%'"
        ).fetchall()
    values = {str(row["key"]): str(row["value"]) for row in rows}
    return {
        "risk_per_trade_enabled": values.get("global_risk_per_trade_enabled", "1") == "1",
        "risk_per_trade_pct": float(values.get("global_risk_per_trade_pct", "2.0")),
        "max_open_risk_enabled": values.get("global_max_open_risk_enabled", "1") == "1",
        "max_open_risk_pct": float(values.get("global_max_open_risk_pct", "40.0")),
        "max_daily_loss_enabled": values.get("global_max_daily_loss_enabled", "1") == "1",
        "max_daily_loss_pct": float(values.get("global_max_daily_loss_pct", "10.0")),
        "daily_profit_target_enabled": values.get("global_daily_profit_target_enabled", "0") == "1",
        "daily_profit_target_pct": float(values.get("global_daily_profit_target_pct", "3.0")),
    }


def set_global_risk_policy(
    *,
    risk_per_trade_enabled: bool,
    risk_per_trade_pct: float,
    max_open_risk_enabled: bool,
    max_open_risk_pct: float,
    max_daily_loss_enabled: bool,
    max_daily_loss_pct: float,
    daily_profit_target_enabled: bool,
    daily_profit_target_pct: float,
) -> dict:
    risk_per_trade_pct = float(risk_per_trade_pct)
    max_open_risk_pct = float(max_open_risk_pct)
    max_daily_loss_pct = float(max_daily_loss_pct)
    daily_profit_target_pct = float(daily_profit_target_pct)

    if not 0.1 <= risk_per_trade_pct <= 2.0:
        raise ValueError("Global risk per trade must be between 0.1% and 2.0%.")
    if not 5.0 <= max_open_risk_pct <= 40.0:
        raise ValueError("Global max open risk must be between 5% and 40%.")
    if not 2.0 <= max_daily_loss_pct <= 10.0:
        raise ValueError("Global daily loss must be between 2% and 10%.")
    if daily_profit_target_pct <= 0:
        raise ValueError("Global daily profit target must be greater than 0%.")

    settings = {
        "global_risk_per_trade_enabled": "1" if risk_per_trade_enabled else "0",
        "global_risk_per_trade_pct": str(risk_per_trade_pct),
        "global_max_open_risk_enabled": "1" if max_open_risk_enabled else "0",
        "global_max_open_risk_pct": str(max_open_risk_pct),
        "global_max_daily_loss_enabled": "1" if max_daily_loss_enabled else "0",
        "global_max_daily_loss_pct": str(max_daily_loss_pct),
        "global_daily_profit_target_enabled": "1" if daily_profit_target_enabled else "0",
        "global_daily_profit_target_pct": str(daily_profit_target_pct),
    }
    with connect() as con:
        for key, value in settings.items():
            con.execute(
                "INSERT INTO server_settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
    return get_global_risk_policy()


def effective_risk_policy(client: ClientRecord) -> dict:
    global_policy = get_global_risk_policy()

    risk_candidates = [2.0]
    if global_policy["risk_per_trade_enabled"]:
        risk_candidates.append(float(global_policy["risk_per_trade_pct"]))
    if bool(client.risk_per_trade_enabled):
        risk_candidates.append(float(client.risk_per_trade_pct))

    open_candidates = [40.0]
    if global_policy["max_open_risk_enabled"]:
        open_candidates.append(float(global_policy["max_open_risk_pct"]))
    if bool(client.max_open_risk_enabled):
        open_candidates.append(float(client.max_open_risk_pct))

    loss_candidates = [10.0]
    if global_policy["max_daily_loss_enabled"]:
        loss_candidates.append(float(global_policy["max_daily_loss_pct"]))
    if bool(client.max_daily_loss_enabled):
        loss_candidates.append(float(client.max_daily_loss_pct))

    if bool(client.daily_profit_target_enabled):
        profit_enabled = True
        profit_target = float(client.daily_profit_target_pct)
        profit_source = "CLIENT"
    elif global_policy["daily_profit_target_enabled"]:
        profit_enabled = True
        profit_target = float(global_policy["daily_profit_target_pct"])
        profit_source = "GLOBAL"
    else:
        profit_enabled = False
        profit_target = 0.0
        profit_source = "OFF"

    return {
        "risk_per_trade_pct": min(risk_candidates),
        "max_open_risk_pct": min(open_candidates),
        "max_daily_loss_pct": min(loss_candidates),
        "daily_profit_target_enabled": profit_enabled,
        "daily_profit_target_pct": profit_target,
        "daily_profit_target_source": profit_source,
    }


def find_by_pairing_code(pairing_code: str) -> ClientRecord | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM clients WHERE pairing_code=?",
            (pairing_code.strip(),),
        ).fetchone()
    return _client(row)


def bind_client(
    client_id: int,
    mt5_login: Optional[int],
    mt5_server: str,
    telegram_username: str,
) -> ClientRecord:
    with connect() as con:
        con.execute(
            """
            UPDATE clients
            SET mt5_login=?, mt5_server=?, telegram_username=?
            WHERE id=?
            """,
            (mt5_login, mt5_server.strip(), telegram_username.strip().lstrip("@"), client_id),
        )
        row = con.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    return _client(row)


def create_session(client_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.execute(
            "INSERT INTO sessions(token,client_id,created_utc) VALUES(?,?,?)",
            (token, client_id, now),
        )
    return token


def client_for_token(token: str) -> ClientRecord | None:
    with connect() as con:
        row = con.execute(
            """
            SELECT c.* FROM sessions s
            JOIN clients c ON c.id=s.client_id
            WHERE s.token=?
            """,
            (token,),
        ).fetchone()
    return _client(row)


def active_clients() -> list[ClientRecord]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM clients WHERE status='ACTIVE' ORDER BY id"
        ).fetchall()
    return [_client(row) for row in rows]


def enqueue_instruction(client_id: int, signal_key: str, payload_json: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        try:
            con.execute(
                """
                INSERT INTO instructions(client_id,signal_key,payload_json,status,created_utc)
                VALUES(?,?,?,?,?)
                """,
                (client_id, signal_key, payload_json, "PENDING", now),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def next_instruction(client_id: int):
    with connect() as con:
        return con.execute(
            """
            SELECT * FROM instructions
            WHERE client_id=? AND status='PENDING'
            ORDER BY id ASC
            LIMIT 1
            """,
            (client_id,),
        ).fetchone()


def acknowledge_instruction(client_id: int, instruction_id: int, status: str, message: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        cur = con.execute(
            """
            UPDATE instructions
            SET status=?, ack_message=?, acked_utc=?
            WHERE id=? AND client_id=? AND status='PENDING'
            """,
            (status.upper(), message[:1000], now, int(instruction_id), int(client_id)),
        )
        return cur.rowcount > 0


def client_by_name(name: str) -> ClientRecord | None:
    with connect() as con:
        row = con.execute("SELECT * FROM clients WHERE name=?", (name.strip(),)).fetchone()
    return _client(row)


def set_news_lock(enabled: bool) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO server_settings(key,value) VALUES('news_lock',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("1" if enabled else "0",),
        )


def news_lock_enabled() -> bool:
    with connect() as con:
        row = con.execute(
            "SELECT value FROM server_settings WHERE key='news_lock'"
        ).fetchone()
    return bool(row and str(row["value"]) == "1")


def upsert_hosted_account(client_id: int, mt5_login: int, mt5_server: str, trading_password: str) -> dict:
    mt5_login = int(mt5_login)
    mt5_server = mt5_server.strip()
    trading_password = trading_password.strip()
    if mt5_login <= 0:
        raise ValueError("MT5 login must be a positive number.")
    if not mt5_server:
        raise ValueError("MT5 server is required.")
    if not trading_password:
        raise ValueError("MT5 trading password is required.")

    ciphertext = encrypt_secret(trading_password)
    now = datetime.now(timezone.utc).isoformat()

    with connect() as con:
        con.execute(
            """
            INSERT INTO hosted_accounts(
                client_id, mt5_login, mt5_server, password_ciphertext,
                status, created_utc, updated_utc
            )
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(client_id) DO UPDATE SET
                mt5_login=excluded.mt5_login,
                mt5_server=excluded.mt5_server,
                password_ciphertext=excluded.password_ciphertext,
                status='PENDING',
                updated_utc=excluded.updated_utc
            """,
            (
                int(client_id),
                mt5_login,
                mt5_server,
                ciphertext,
                "PENDING",
                now,
                now,
            ),
        )
        row = con.execute(
            """
            SELECT id, client_id, mt5_login, mt5_server, status, created_utc, updated_utc
            FROM hosted_accounts WHERE client_id=?
            """,
            (int(client_id),),
        ).fetchone()
    return dict(row)


def hosted_account_for_client(client_id: int) -> dict | None:
    with connect() as con:
        row = con.execute(
            """
            SELECT id, client_id, mt5_login, mt5_server, status,
                   terminal_path, worker_pid, last_error, last_seen_utc,
                   account_balance, account_equity, created_utc, updated_utc
            FROM hosted_accounts WHERE client_id=?
            """,
            (int(client_id),),
        ).fetchone()
    return dict(row) if row else None


def hosted_account_secret_for_client(client_id: int) -> dict | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM hosted_accounts WHERE client_id=?",
            (int(client_id),),
        ).fetchone()
    return dict(row) if row else None


def list_hosted_accounts() -> list[dict]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT h.id, h.client_id, c.name AS client_name, h.mt5_login, h.mt5_server,
                   h.status, h.terminal_path, h.worker_pid, h.last_error,
                   h.last_seen_utc, h.account_balance, h.account_equity,
                   h.created_utc, h.updated_utc
            FROM hosted_accounts h
            JOIN clients c ON c.id=h.client_id
            ORDER BY h.updated_utc DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def set_hosted_account_status(client_id: int, status: str) -> None:
    status = status.upper()
    if status not in {"PENDING", "APPROVED", "PROVISIONED", "CONNECTING", "ACTIVE", "FAILED", "DISABLED"}:
        raise ValueError("Invalid hosted account status.")
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        cur = con.execute(
            "UPDATE hosted_accounts SET status=?, updated_utc=? WHERE client_id=?",
            (status, now, int(client_id)),
        )
        if cur.rowcount == 0:
            raise ValueError("Hosted account not found.")


def client_by_id(client_id: int) -> ClientRecord | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM clients WHERE id=?",
            (int(client_id),),
        ).fetchone()
    return _client(row)


def set_hosted_runtime(
    client_id: int,
    *,
    terminal_path: str | None = None,
    worker_pid: int | None | object = ...,
    last_error: str | None = None,
    last_seen_utc: str | None = None,
    account_balance: float | None | object = ...,
    account_equity: float | None | object = ...,
) -> None:
    fields = []
    values = []

    if terminal_path is not None:
        fields.append("terminal_path=?")
        values.append(str(terminal_path))
    if worker_pid is not ...:
        fields.append("worker_pid=?")
        values.append(None if worker_pid is None else int(worker_pid))
    if last_error is not None:
        fields.append("last_error=?")
        values.append(str(last_error)[:2000])
    if last_seen_utc is not None:
        fields.append("last_seen_utc=?")
        values.append(str(last_seen_utc))
    if account_balance is not ...:
        fields.append("account_balance=?")
        values.append(None if account_balance is None else float(account_balance))
    if account_equity is not ...:
        fields.append("account_equity=?")
        values.append(None if account_equity is None else float(account_equity))

    if not fields:
        return

    fields.append("updated_utc=?")
    values.append(datetime.now(timezone.utc).isoformat())
    values.append(int(client_id))

    with connect() as con:
        cur = con.execute(
            f"UPDATE hosted_accounts SET {', '.join(fields)} WHERE client_id=?",
            tuple(values),
        )
        if cur.rowcount == 0:
            raise ValueError("Hosted account not found.")


def set_execution_mode(client_id: int, mode: str) -> None:
    mode = mode.upper().strip()
    if mode not in {"CLIENT_PC", "HOSTED"}:
        raise ValueError("Execution mode must be CLIENT_PC or HOSTED.")
    with connect() as con:
        cur = con.execute(
            "UPDATE clients SET execution_mode=? WHERE id=?",
            (mode, int(client_id)),
        )
        if cur.rowcount == 0:
            raise ValueError("Client not found.")


def link_telegram_chat(pairing_code: str, telegram_chat_id: int, telegram_username: str = "") -> ClientRecord:
    client = find_by_pairing_code(pairing_code)
    if client is None:
        raise ValueError("Invalid pairing code.")
    with connect() as con:
        con.execute(
            """
            UPDATE clients
            SET telegram_chat_id=?, telegram_username=?
            WHERE id=?
            """,
            (
                int(telegram_chat_id),
                telegram_username.strip().lstrip("@"),
                int(client.id),
            ),
        )
        row = con.execute("SELECT * FROM clients WHERE id=?", (client.id,)).fetchone()
    return _client(row)


def client_by_telegram_chat(telegram_chat_id: int) -> ClientRecord | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM clients WHERE telegram_chat_id=?",
            (int(telegram_chat_id),),
        ).fetchone()
    return _client(row)


def ensure_subscription(client_id: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.execute(
            """
            INSERT OR IGNORE INTO subscriptions(
                client_id, plan_code, status, starts_utc, expires_utc, auto_renew, updated_utc
            )
            VALUES(?, 'STARTER', 'TRIAL', '', '', 0, ?)
            """,
            (int(client_id), now),
        )
        row = con.execute(
            "SELECT * FROM subscriptions WHERE client_id=?",
            (int(client_id),),
        ).fetchone()
    return dict(row)


def set_subscription(
    client_id: int,
    *,
    plan_code: str,
    status: str,
    starts_utc: str,
    expires_utc: str,
    auto_renew: bool = False,
) -> dict:
    plan_code = plan_code.upper().strip()
    status = status.upper().strip()
    if status not in {"TRIAL", "ACTIVE", "PAST_DUE", "EXPIRED", "CANCELLED"}:
        raise ValueError("Invalid subscription status.")
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.execute(
            """
            INSERT INTO subscriptions(
                client_id, plan_code, status, starts_utc, expires_utc, auto_renew, updated_utc
            )
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(client_id) DO UPDATE SET
                plan_code=excluded.plan_code,
                status=excluded.status,
                starts_utc=excluded.starts_utc,
                expires_utc=excluded.expires_utc,
                auto_renew=excluded.auto_renew,
                updated_utc=excluded.updated_utc
            """,
            (
                int(client_id),
                plan_code,
                status,
                starts_utc,
                expires_utc,
                1 if auto_renew else 0,
                now,
            ),
        )
        row = con.execute(
            "SELECT * FROM subscriptions WHERE client_id=?",
            (int(client_id),),
        ).fetchone()
    return dict(row)


def subscription_for_client(client_id: int) -> dict:
    return ensure_subscription(client_id)


def subscription_access(client_id: int) -> dict:
    sub = subscription_for_client(client_id)
    status = str(sub.get("status", "TRIAL") or "TRIAL").upper()
    expires_raw = str(sub.get("expires_utc", "") or "").strip()

    if status in {"PAST_DUE", "EXPIRED", "CANCELLED"}:
        return {
            "allowed": False,
            "reason": f"SUBSCRIPTION_{status}",
            "subscription": sub,
        }

    if expires_raw:
        try:
            expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= expires.astimezone(timezone.utc):
                return {
                    "allowed": False,
                    "reason": "SUBSCRIPTION_EXPIRED",
                    "subscription": sub,
                }
        except ValueError:
            return {
                "allowed": False,
                "reason": "SUBSCRIPTION_EXPIRY_INVALID",
                "subscription": sub,
            }

    return {
        "allowed": True,
        "reason": "OK",
        "subscription": sub,
    }


def create_payment_request(
    client_id: int,
    *,
    plan_code: str,
    amount: float,
    currency: str = "USD",
    provider: str = "UNSET",
    checkout_url: str = "",
    provider_reference: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        cur = con.execute(
            """
            INSERT INTO payment_requests(
                client_id, kind, plan_code, amount, currency, provider,
                provider_reference, status, checkout_url, created_utc, updated_utc
            )
            VALUES(?, 'RENEWAL', ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
            """,
            (
                int(client_id),
                plan_code.upper().strip(),
                float(amount),
                currency.upper().strip(),
                provider.upper().strip(),
                provider_reference,
                checkout_url,
                now,
                now,
            ),
        )
        row = con.execute(
            "SELECT * FROM payment_requests WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)


def latest_payment_request(client_id: int) -> dict | None:
    with connect() as con:
        row = con.execute(
            """
            SELECT * FROM payment_requests
            WHERE client_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (int(client_id),),
        ).fetchone()
    return dict(row) if row else None
