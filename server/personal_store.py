"""Personal execution state, separate from client registration and subscriptions."""
from __future__ import annotations
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .store import DB_PATH


def settings_path():
    return Path(os.getenv("GOLD_AI_STATE_DIR", str(DB_PATH.parent))) / "personal_account.json"


def validate_settings(settings):
    path = Path(str(settings.get("terminal_path", ""))).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Select the installed MT5 terminal executable.")
    login = int(settings.get("login", 0))
    server = str(settings.get("server", "")).strip()
    if login <= 0 or not server:
        raise ValueError("Detect the logged-in MT5 account or enter its login and broker server.")
    result = {"terminal_path": str(path.resolve()), "login": login, "server": server}
    for key, default, low, high in (("risk_per_trade_pct", .9, .1, 2), ("max_open_risk_pct", 40, 5, 40), ("max_daily_loss_pct", 5, 2, 10)):
        value = float(settings.get(key, default))
        if not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high} percent.")
        result[key] = value
    return result


def save_settings(settings):
    result = validate_settings(settings)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temp.replace(path)
    return result


def load_settings():
    return validate_settings(json.loads(settings_path().read_text(encoding="utf-8")))


def write_status(name, **values):
    path = Path.cwd() / "logs" / (name + "_status.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"updated": time.time(), **values}), encoding="utf-8")
    temp.replace(path)


@contextmanager
def connection():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.execute("CREATE TABLE IF NOT EXISTS owner_signals (id INTEGER PRIMARY KEY, signal_key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS personal_deliveries (account TEXT NOT NULL, signal_key TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', updated REAL NOT NULL, PRIMARY KEY(account,signal_key))")
        yield con
        con.commit()
    finally:
        con.close()


def publish_signal(key, payload):
    with connection() as con:
        con.execute("INSERT OR IGNORE INTO owner_signals(signal_key,payload,created) VALUES(?,?,?)", (key, json.dumps(payload, default=str), time.time()))


def next_signal(after_id, since):
    with connection() as con:
        row = con.execute("SELECT * FROM owner_signals WHERE id>? AND created>=? ORDER BY id LIMIT 1", (after_id, since)).fetchone()
        return dict(row) if row else None


def claim_signal(account, key):
    # Persist BEFORE order submission. A crash leaves an uncertain submission for
    # manual reconciliation, never an automatic retry that could duplicate a trade.
    with connection() as con:
        return con.execute("INSERT OR IGNORE INTO personal_deliveries(account,signal_key,state,updated) VALUES(?,?,'SUBMITTING',?)", (account, key, time.time())).rowcount == 1


def finish_signal(account, key, state, message):
    with connection() as con:
        con.execute("UPDATE personal_deliveries SET state=?,message=?,updated=? WHERE account=? AND signal_key=?", (state, message, time.time(), account, key))
