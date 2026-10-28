"""Explicitly selected local MT5 account; never signs up or logs in a client."""
from __future__ import annotations
import json
import os
import time
import uuid
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
import MetaTrader5 as mt5
from .hosted_executor import execute_instruction
from .personal_store import load_settings, write_status, next_signal, claim_signal, finish_signal
from .store import list_clients, list_hosted_accounts, effective_risk_policy, news_lock_enabled
from config import DEMO_MAX_SIGNAL_AGE_MINUTES
from .reconnect import TemporaryConnectionError, SafetyStop, RetryState


def _verify_terminal_identity(settings, stop=None, trading=True):
    if stop is not None and stop.is_set():
        raise RuntimeError("Personal trading stopped.")
    account = mt5.account_info()
    terminal = mt5.terminal_info()
    if account is None or terminal is None or not getattr(terminal, "connected", False):
        raise TemporaryConnectionError("Personal MT5 terminal is disconnected.")
    if int(account.login) != settings["login"] or str(account.server) != settings["server"]:
        raise SafetyStop("MT5 account changed. Stopping personal trading; select the intended account in Personal MT5 Settings.")
    if trading:
        if not getattr(terminal, "trade_allowed", False) or getattr(terminal, "tradeapi_disabled", False):
            raise SafetyStop("Enable Algo Trading and Python API trading in the selected MT5 terminal.")
        if not getattr(account, "trade_allowed", False) or not getattr(account, "trade_expert", False):
            raise SafetyStop("The selected MT5 account does not permit automated trading.")
        if float(account.equity) <= 0:
            raise SafetyStop("Personal account equity must be positive.")
    return account


def verify_account(settings, stop=None, trading=True):
    account = _verify_terminal_identity(settings, stop, trading)
    if trading:
        for client in list_clients():
            if client.mt5_login == settings["login"] and client.mt5_server == settings["server"] and client.status == "ACTIVE":
                raise SafetyStop(f"Pause the matching client '{client.name}' and close its Client/hosted worker before using Personal Trading, to avoid duplicate orders.")
            if client.status == "ACTIVE" and getattr(client, "id", None) is not None:
                from .azt_store import list_accounts
                for binding in list_accounts(client.id):
                    if binding["status"] == "ACTIVE" and int(binding["login"]) == settings["login"] and str(binding["server"]) == settings["server"]:
                        raise SafetyStop(f"Pause the matching client '{client.name}' and close all its account workers before Personal Trading, to avoid duplicate orders.")
        for hosted in list_hosted_accounts():
            if int(hosted.get("mt5_login") or 0) == settings["login"] and hosted.get("mt5_server") == settings["server"] and hosted.get("status") in {"ACTIVE", "CONNECTING"}:
                raise SafetyStop("Stop the hosted worker for this MT5 account before using Personal Trading.")
    return account


def attach(path):
    if not mt5.initialize(path, timeout=10000):
        raise TemporaryConnectionError(f"Could not connect to selected MT5: {mt5.last_error()}")


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
        latest = effective_risk_policy(SimpleNamespace(**settings, risk_per_trade_enabled=True, max_open_risk_enabled=True, max_daily_loss_enabled=True, daily_profit_target_enabled=False, daily_profit_target_pct=0))
        if any(latest.get(field) != policy.get(field) for field in ("risk_per_trade_pct", "max_open_risk_pct", "max_daily_loss_pct", "daily_profit_target_enabled", "daily_profit_target_pct")):
            raise SafetyStop("Risk policy changed before order submission; wait for a fresh signal.")
        # Database reads above can block. Identity/Stop/age must be the final
        # checks, after those reads, immediately before order_send.
        _verify_terminal_identity(settings, stop)
        age_now = (datetime.now(timezone.utc)-setup).total_seconds()
        if age_now < -60 or age_now > DEMO_MAX_SIGNAL_AGE_MINUTES * 60:
            raise SafetyStop("Signal expired before order submission.")
    result = execute_instruction(payload, policy["risk_per_trade_pct"], policy["max_open_risk_pct"], policy["max_daily_loss_pct"], policy["daily_profit_target_enabled"], policy["daily_profit_target_pct"], max_single_risk_pct=2.0, before_send=guard, include_all_positions=True, strict_history=True)
    from .trade_events import SignalOutcome
    return SignalOutcome("EXECUTED" if result.sent else "REJECTED", f"{result.message}; ticket={result.ticket}; risk={result.planned_risk_pct:.3f}%; volume={result.volume}", getattr(result, 'details', {}))


def _runtime_alert(event_key, state, account, message):
    try:
        from . import personal_store
        from .telegram_notifications import enqueue_owner_event
        from .client_notifications import record_system_event
        record_system_event('PERSONAL_'+state,f'{account}: {message}',event_key=event_key,database=personal_store.DB_PATH)
        enqueue_owner_event(event_key, f"AZT PERSONAL {state}\nAccount: {account}\n{message}", database=personal_store.DB_PATH,
                            event={'kind':'RUNTIME','account':account,'state':state,'message':message})
    except Exception as exc:
        logging.warning("Personal runtime alert could not be queued (%s)", type(exc).__name__)


_telemetry_clocks = {}


def _capture_telemetry(key):
    try:
        from broker.clock import BrokerClock
        from broker.symbols import resolve_symbol
        from .trade_telemetry import capture_mt5, ingest_snapshot
        from . import personal_store
        account, terminal = mt5.account_info(), mt5.terminal_info()
        if not isinstance(getattr(account, "login", None), int):
            return  # A valid attached identity is required before any DB write.
        symbol = resolve_symbol(mt5, "GOLD")
        clock_key = (key, str(getattr(terminal, "path", "")), symbol)
        clock = _telemetry_clocks.get(clock_key)
        if clock is None:
            clock = BrokerClock.detect(mt5, symbol)
            _telemetry_clocks[clock_key] = clock
        clock.validate_tick(mt5.symbol_info_tick(symbol))
        result = ingest_snapshot(None, key, capture_mt5(mt5, clock_offset_seconds=clock.offset_seconds), database=personal_store.DB_PATH)
        from .client_notifications import enqueue_trade_event
        for trade in result["new_open"] + result["new_closed"] + result.get('new_stop_updates', []):
            trade.update(account_key=key, currency=getattr(account, "currency", ""))
            event_key=trade.get('event_key') or f"personal-trade:{key}:{trade['state']}:{trade['ticket']}"
            enqueue_trade_event(None, trade, event_key=event_key, database=personal_store.DB_PATH)
    except Exception as exc:
        logging.warning("Personal read-only telemetry unavailable (%s); prior snapshot retained.", type(exc).__name__)


def run(stop):
    lock = None
    run_id = uuid.uuid4().hex
    key = "not connected"
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
        connected = False
        retries = RetryState()
        since, cursor = time.time(), 0
        last_result = "Waiting for fresh signals"
        telemetry_due = 0
        while not stop.is_set():
            try:
                if not connected:
                    write_status("personal", state="CONNECTING", desired=True, login=settings["login"], server=settings["server"])
                    attach(settings["terminal_path"])
                    account = verify_account(settings, stop)
                    # No backlog on Start OR reconnect. Existing durable claims
                    # remain intact, including uncertain previous submissions.
                    since, cursor = time.time(), 0
                    recovered = retries.recovered()
                    connected = True
                    state = "RECOVERED" if recovered else "READY"
                    print(f"PERSONAL MT5 {state}: {key}", flush=True)
                    _runtime_alert(f"personal-{state.lower()}:{run_id}:{since}", state, key,
                                   "Connected and waiting for fresh signals. No order has been placed by this readiness event.")
                account = verify_account(settings, stop)
            except TemporaryConnectionError as exc:
                connected = False
                mt5.shutdown()
                _telemetry_clocks.clear()
                from broker.clock import _clocks
                _clocks.clear()
                delay = retries.failed()
                write_status("personal", state=retries.state, desired=True, retry_in=delay,
                             failures=retries.failures, message=str(exc))
                if retries.should_alert():
                    _runtime_alert(f"personal-disconnected:{run_id}:{retries.failures}", retries.state, key,
                                   "MT5 connection unavailable; desired trading remains enabled and reconnect continues.")
                stop.wait(delay)
                continue
            write_status("personal", state="READY", desired=True, login=int(account.login), server=str(account.server), equity=float(account.equity), message=f"{key}: {last_result}")
            if time.monotonic() >= telemetry_due:
                _capture_telemetry(key)
                telemetry_due = time.monotonic() + 10
            row = next_signal(cursor, since)
            if row is None:
                stop.wait(1)
                continue
            cursor = row["id"]
            if not claim_signal(key, row["signal_key"]):
                continue
            details = {}
            try:
                outcome = execute_signal(row, settings, stop)
                state, message = outcome
                details = getattr(outcome, 'details', {})
            except Exception as exc:
                # An exception around submission can be ambiguous; never auto retry.
                state, message = "ERROR_REVIEW", str(exc)
            finish_signal(key, row["signal_key"], state, message, details=details)
            if state == "EXECUTED":
                try:
                    import re
                    from .trade_telemetry import record_execution
                    from . import personal_store
                    ticket = re.search(r"ticket=(\d+)", message)
                    risk = re.search(r"risk=([0-9.]+)%", message)
                    if ticket:
                        record_execution(None, key, ticket.group(1), json.loads(row["payload"]),
                                         risk_pct=float(risk.group(1)) if risk else None, trade_details=details, database=personal_store.DB_PATH)
                except Exception as exc:
                    logging.warning("Execution metadata unavailable (%s); trade result remains saved.", type(exc).__name__)
            last_result = f"{state}: {message}"
            print(f"PERSONAL {state}: {row['signal_key']} | {message}", flush=True)
        write_status("personal", state="STOPPED", desired=False, message="Personal trading stopped; positions remain at the broker.")
    except Exception as exc:
        if stop.is_set() and isinstance(exc, RuntimeError) and str(exc) == "Personal trading stopped.":
            write_status("personal", state="STOPPED", desired=False, message="Personal trading stopped; positions remain at the broker.")
            return
        write_status("personal", state="ERROR", desired=False, message=str(exc))
        _runtime_alert(f"personal-error:{run_id}", "ERROR", key, str(exc))
        raise
    finally:
        mt5.shutdown()
        if lock:
            lock.close()
