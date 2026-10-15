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
    created_utc: str
    risk_per_trade_pct: float = 0.9
    max_open_risk_pct: float = 40.0
    max_daily_loss_pct: float = 5.0


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
            created_utc TEXT NOT NULL,
            risk_per_trade_pct REAL NOT NULL DEFAULT 0.9,
            max_open_risk_pct REAL NOT NULL DEFAULT 40.0,
            max_daily_loss_pct REAL NOT NULL DEFAULT 5.0
        )
        """
    )
    cols = {row["name"] for row in con.execute("PRAGMA table_info(clients)").fetchall()}
    migrations = {
        "risk_per_trade_pct": "ALTER TABLE clients ADD COLUMN risk_per_trade_pct REAL NOT NULL DEFAULT 0.9",
        "max_open_risk_pct": "ALTER TABLE clients ADD COLUMN max_open_risk_pct REAL NOT NULL DEFAULT 40.0",
        "max_daily_loss_pct": "ALTER TABLE clients ADD COLUMN max_daily_loss_pct REAL NOT NULL DEFAULT 5.0",
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
    con.execute(
        "INSERT OR IGNORE INTO server_settings(key,value) VALUES('news_lock','0')"
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


def set_client_risk(name: str, risk_per_trade_pct: float, max_open_risk_pct: float, max_daily_loss_pct: float) -> ClientRecord:
    risk_per_trade_pct = float(risk_per_trade_pct)
    max_open_risk_pct = float(max_open_risk_pct)
    max_daily_loss_pct = float(max_daily_loss_pct)
    if not 0.1 <= risk_per_trade_pct <= 2.0:
        raise ValueError("Risk per trade must be between 0.1% and 2.0%.")
    if not 5.0 <= max_open_risk_pct <= 40.0:
        raise ValueError("Max overall open risk must be between 5% and 40%.")
    if not 2.0 <= max_daily_loss_pct <= 10.0:
        raise ValueError("Max daily loss must be between 2% and 10%.")
    with connect() as con:
        cur = con.execute(
            """
            UPDATE clients
            SET risk_per_trade_pct=?, max_open_risk_pct=?, max_daily_loss_pct=?
            WHERE name=?
            """,
            (risk_per_trade_pct, max_open_risk_pct, max_daily_loss_pct, name.strip()),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Unknown client: {name}")
        row = con.execute("SELECT * FROM clients WHERE name=?", (name.strip(),)).fetchone()
    return _client(row)


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
            SELECT id, client_id, mt5_login, mt5_server, status, created_utc, updated_utc
            FROM hosted_accounts WHERE client_id=?
            """,
            (int(client_id),),
        ).fetchone()
    return dict(row) if row else None


def list_hosted_accounts() -> list[dict]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT h.id, h.client_id, c.name AS client_name, h.mt5_login, h.mt5_server,
                   h.status, h.created_utc, h.updated_utc
            FROM hosted_accounts h
            JOIN clients c ON c.id=h.client_id
            ORDER BY h.updated_utc DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def set_hosted_account_status(client_id: int, status: str) -> None:
    status = status.upper()
    if status not in {"PENDING", "APPROVED", "PROVISIONED", "ACTIVE", "FAILED", "DISABLED"}:
        raise ValueError("Invalid hosted account status.")
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        cur = con.execute(
            "UPDATE hosted_accounts SET status=?, updated_utc=? WHERE client_id=?",
            (status, now, int(client_id)),
        )
        if cur.rowcount == 0:
            raise ValueError("Hosted account not found.")
