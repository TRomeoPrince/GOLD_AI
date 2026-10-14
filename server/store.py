from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "gold_ai_server.db"


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
            created_utc TEXT NOT NULL
        )
        """
    )
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
    con.commit()
    return con


def create_client(name: str) -> tuple[ClientRecord, str]:
    code = secrets.token_urlsafe(8)
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        cur = con.execute(
            "INSERT INTO clients(name,status,pairing_code,created_utc) VALUES(?,?,?,?)",
            (name.strip(), "ACTIVE", code, now),
        )
        row = con.execute("SELECT * FROM clients WHERE id=?", (cur.lastrowid,)).fetchone()
    return ClientRecord(**dict(row)), code


def list_clients() -> list[ClientRecord]:
    with connect() as con:
        rows = con.execute("SELECT * FROM clients ORDER BY id").fetchall()
    return [ClientRecord(**dict(row)) for row in rows]


def set_status(name: str, status: str) -> None:
    status = status.upper()
    if status not in {"ACTIVE", "PAUSED", "REVOKED", "EXPIRED"}:
        raise ValueError("Status must be ACTIVE, PAUSED, REVOKED or EXPIRED.")
    with connect() as con:
        cur = con.execute("UPDATE clients SET status=? WHERE name=?", (status, name))
        if cur.rowcount == 0:
            raise ValueError(f"Unknown client: {name}")


def find_by_pairing_code(pairing_code: str) -> ClientRecord | None:
    with connect() as con:
        row = con.execute(
            "SELECT * FROM clients WHERE pairing_code=?",
            (pairing_code.strip(),),
        ).fetchone()
    return ClientRecord(**dict(row)) if row else None


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
            (
                mt5_login,
                mt5_server.strip(),
                telegram_username.strip().lstrip("@"),
                client_id,
            ),
        )
        row = con.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    return ClientRecord(**dict(row))


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
    return ClientRecord(**dict(row)) if row else None


def active_clients() -> list[ClientRecord]:
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM clients WHERE status='ACTIVE' ORDER BY id"
        ).fetchall()
    return [ClientRecord(**dict(row)) for row in rows]


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
        row = con.execute(
            "SELECT * FROM clients WHERE name=?",
            (name.strip(),),
        ).fetchone()
    return ClientRecord(**dict(row)) if row else None
