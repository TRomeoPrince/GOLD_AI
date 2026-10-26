"""Explicitly selected local MT5 account; never signs up or logs in a client."""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone
from types import SimpleNamespace
import MetaTrader5 as mt5
from .hosted_executor import execute_instruction
from .personal_store import load_settings, write_status, next_signal, claim_signal, finish_signal
from .store import list_clients, list_hosted_accounts, effective_risk_policy, news_lock_enabled
from config import DEMO_MAX_SIGNAL_AGE_MINUTES


def verify_account(settings, stop=None, trading=True):
    if stop is not None and stop.is_set():
        raise RuntimeError("Personal trading stopped.")
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    if account is None or terminal is None or not getattr(terminal, "connected", False):
        raise RuntimeError("Personal MT5 terminal is disconnected.")
    if int(account.login) != settings["login"] or str(account.server) != settings["server"]:
        raise RuntimeError("MT5 account changed. Stopping personal trading; select the intended account in Personal MT5 Settings.")
    if trading:
        if not getattr(terminal, "trade_allowed", False) or getattr(terminal, "tradeapi_disabled", False):
            raise RuntimeError("Enable Algo Trading and Python API trading in the selected MT5 terminal.")
        if not getattr(account, "trade_allowed", False) or not getattr(account, "trade_expert", False):
            raise RuntimeError("The selected MT5 account does not permit automated trading.")
        if float(account.equity) <= 0:
            raise RuntimeError("Personal account equity must be positive.")
        for client in list_clients():
            if client.mt5_login == settings["login"] and client.mt5_server == settings["server"] and client.status == "ACTIVE":
                raise RuntimeError(f"Pause the matching client '{client.name}' and close its Client/hosted worker before using Personal Trading, to avoid duplicate orders.")
        for hosted in list_hosted_accounts():
            if int(hosted.get("mt5_login") or 0) == settings["login"] and hosted.get("mt5_server") == settings["server"] and hosted.get("status") in {"ACTIVE", "CONNECTING"}:
                raise RuntimeError("Stop the hosted worker for this MT5 account before using Personal Trading.")
    return account


def attach(path):
    if not mt5.initialize(path, timeout=10000):
        raise RuntimeError(f"Could not connect to selected MT5: {mt5.last_error()}")


def probe():
    try:
        attach(os.environ["GOLD_AI_PERSONAL_PROBE_TERMINAL"])
        account, terminal = mt5.account_info(), mt5.terminal_info()
        if account is None or terminal is None:
            raise RuntimeError("Log in to the selected MT5 terminal first.")
        write_status("personal_probe", state="DETECTED", login=int(account.login), server=str(account.server), balance=float(account.balance), currency=str(account.currency))
    except Exception as exc:
        write_status("personal_probe", state="ERROR", message=str(exc))
        raise
    finally:
        mt5.shutdown()


def execute_signal(row, settings, stop):
    verify_account(settings, stop)
    if news_lock_enabled():
        return "SKIPPED", "News lock is enabled."
    payload = json.loads(row["payload"])
    setup = datetime.fromisoformat(str(payload["setup_time"]).replace("Z", "+00:00"))
    if setup.tzinfo is None:
        setup = setup.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc)-setup).total_seconds()
    if age < -60 or age > DEMO_MAX_SIGNAL_AGE_MINUTES * 60:
        return "SKIPPED", "Signal is outside its permitted age."
    policy = effective_risk_policy(SimpleNamespace(**settings, risk_per_trade_enabled=True, max_open_risk_enabled=True, max_daily_loss_enabled=True, daily_profit_target_enabled=False, daily_profit_target_pct=0))
    def guard():
        verify_account(settings, stop)
        if news_lock_enabled():
            raise RuntimeError("News lock enabled before order submission.")
    result = execute_instruction(payload, policy["risk_per_trade_pct"], policy["max_open_risk_pct"], policy["max_daily_loss_pct"], policy["daily_profit_target_enabled"], policy["daily_profit_target_pct"], max_single_risk_pct=2.0, before_send=guard, include_all_positions=True, strict_history=True)
    return ("EXECUTED" if result.sent else "REJECTED"), f"{result.message}; ticket={result.ticket}; risk={result.planned_risk_pct:.3f}%; volume={result.volume}"


def run(stop):
    lock = None
    try:
        settings = load_settings()
        import hashlib
        import msvcrt
        from pathlib import Path
        key = f"{settings['server']}|{settings['login']}"
        lock_dir = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "GOLD_AI" / "personal_locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock = open(lock_dir / (hashlib.sha256(key.encode()).hexdigest()+".lock"), "a+b")
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Personal trading is already running for this MT5 account.") from exc
        write_status("personal", state="CONNECTING", login=settings["login"], server=settings["server"])
        attach(settings["terminal_path"])
        verify_account(settings, stop)
        since, cursor = time.time(), 0  # No backlog trades on Start or restart.
        last_result = "Waiting for fresh signals"
        print(f"PERSONAL MT5 READY: {key}", flush=True)
        while not stop.is_set():
            account = verify_account(settings, stop)
            write_status("personal", state="READY", login=int(account.login), server=str(account.server), equity=float(account.equity), message=f"{key}: {last_result}")
            row = next_signal(cursor, since)
            if row is None:
                stop.wait(1)
                continue
            cursor = row["id"]
            if not claim_signal(key, row["signal_key"]):
                continue
            try:
                state, message = execute_signal(row, settings, stop)
            except Exception as exc:
                # An exception around submission can be ambiguous; never auto retry.
                state, message = "ERROR_REVIEW", str(exc)
            finish_signal(key, row["signal_key"], state, message)
            last_result = f"{state}: {message}"
            print(f"PERSONAL {state}: {row['signal_key']} | {message}", flush=True)
        write_status("personal", state="STOPPED", message="Personal trading stopped; positions remain at the broker.")
    except Exception as exc:
        write_status("personal", state="ERROR", message=str(exc))
        raise
    finally:
        mt5.shutdown()
        if lock:
            lock.close()
