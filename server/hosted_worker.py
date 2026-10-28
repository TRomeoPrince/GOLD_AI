from __future__ import annotations

import argparse
import json
import os
import time
import threading
import logging
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

from .credential_vault import decrypt_secret
from .hosted_executor import execute_instruction
from .reconnect import TemporaryConnectionError, SafetyStop, RetryState
from .personal_store import claim_signal, connection as ledger_connection
from config import DEMO_MAX_SIGNAL_AGE_MINUTES
from .store import (
    acknowledge_instruction,
    client_by_id,
    effective_risk_policy,
    hosted_account_secret_for_client,
    next_instruction,
    set_hosted_account_status,
    set_hosted_runtime,
    subscription_access,
    news_lock_enabled,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _attach_mt5(terminal_path: Path) -> None:
    if not mt5.initialize(str(terminal_path), timeout=10000, portable=True):
        raise TemporaryConnectionError("Hosted MT5 IPC connection unavailable.")


def connect_mt5(client_id: int, *, reconnect=False):
    set_hosted_account_status(client_id, "CONNECTING")
    set_hosted_runtime(
        client_id,
        last_error="",
        last_seen_utc=utc_now(),
        account_balance=None,
        account_equity=None,
    )
    hosted = hosted_account_secret_for_client(client_id)
    if not hosted:
        raise SafetyStop("Hosted MT5 account not found.")

    terminal_path = str(hosted.get("terminal_path") or "")
    if not terminal_path or not Path(terminal_path).exists():
        raise SafetyStop("Provisioned MT5 terminal was not found.")

    terminal = Path(terminal_path)

    # Attach the explicitly provisioned terminal without killing any existing
    # process or broker position. initialize opens it if it is not already up.
    _attach_mt5(terminal)
    account = mt5.account_info()
    if reconnect and account is not None and (int(account.login) != int(hosted["mt5_login"]) or str(account.server) != str(hosted["mt5_server"])):
        raise SafetyStop("Hosted MT5 account changed; manual review required.")
    if account is None or int(account.login) != int(hosted["mt5_login"]) or str(account.server) != str(hosted["mt5_server"]):
        password = decrypt_secret(str(hosted["password_ciphertext"]))
        try:
            if not mt5.login(int(hosted["mt5_login"]), password=password, server=str(hosted["mt5_server"]), timeout=10000):
                raise TemporaryConnectionError("Hosted MT5 login unavailable.")
        finally:
            password = ""
    return hosted, verify_hosted_account(hosted)


def verify_hosted_account(hosted):
    account, terminal = mt5.account_info(), mt5.terminal_info()
    if account is None or terminal is None or not bool(getattr(terminal, "connected", False)):
        raise TemporaryConnectionError("Hosted MT5 connection unavailable.")
    if int(account.login) != int(hosted["mt5_login"]) or str(account.server) != str(hosted["mt5_server"]):
        raise SafetyStop("Hosted MT5 account changed; manual review required.")
    if not bool(getattr(terminal, "trade_allowed", False)) or bool(getattr(terminal, "tradeapi_disabled", False)):
        raise SafetyStop("Hosted MT5 Algo Trading or Python API trading is disabled.")
    if not bool(getattr(account, "trade_allowed", False)) or not bool(getattr(account, "trade_expert", False)):
        raise SafetyStop("Hosted account does not permit automated trading.")
    return account


def _notify(client_id, text, event_key):
    try:
        from .client_notifications import enqueue_client_message
        enqueue_client_message(client_id, text, event_key=event_key)
    except Exception as exc:
        logging.warning("Hosted notification unavailable (%s).", type(exc).__name__)


def _capture_hosted(client_id, key, clocks):
    try:
        from broker.clock import BrokerClock
        from broker.symbols import resolve_symbol
        from .trade_telemetry import capture_mt5, ingest_snapshot
        from .store import DB_PATH
        symbol = resolve_symbol(mt5, "GOLD")
        clock = clocks.get(symbol)
        if clock is None:
            clock = BrokerClock.detect(mt5, symbol)
            clocks[symbol] = clock
        clock.validate_tick(mt5.symbol_info_tick(symbol))
        result = ingest_snapshot(client_id, key, capture_mt5(mt5, clock_offset_seconds=clock.offset_seconds), database=DB_PATH)
        from .client_notifications import enqueue_trade_event
        account = mt5.account_info()
        for row in result["new_open"] + result["new_closed"]:
            row.update(account_key=key, currency=getattr(account, "currency", ""))
            enqueue_trade_event(client_id, row, event_key=f"hosted-trade:{key}:{row['state']}:{row['ticket']}")
    except Exception as exc:
        logging.warning("Hosted read-only telemetry unavailable (%s); retaining prior snapshot.", type(exc).__name__)


def _finish_claim(account_key, signal_key, state, message):
    with ledger_connection() as con:
        con.execute("UPDATE personal_deliveries SET state=?,message=?,updated=? WHERE account=? AND signal_key=?", (state, message, time.time(), account_key, signal_key))


def signal_is_fresh(payload, *, now=None):
    try:
        setup = datetime.fromisoformat(str(payload["setup_time"]).replace("Z", "+00:00"))
        if setup.tzinfo is None:
            return False
        age = ((now or datetime.now(timezone.utc)) - setup).total_seconds()
        return -60 <= age <= DEMO_MAX_SIGNAL_AGE_MINUTES * 60
    except (KeyError, ValueError, TypeError):
        return False


def _acquire_account_lock(hosted):
    import hashlib
    import msvcrt
    key = f"{hosted['mt5_server']}|{hosted['mt5_login']}"
    directory = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "GOLD_AI" / "personal_locks"
    directory.mkdir(parents=True, exist_ok=True)
    handle = open(directory / (hashlib.sha256(key.encode()).hexdigest() + ".lock"), "a+b")
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        handle.close()
        raise SafetyStop("An AZT worker already controls this MT5 account.") from exc
    return handle


def run(client_id: int, stop=None) -> None:
    stop = stop or threading.Event()
    retries, clocks = RetryState(), {}
    connected, ever_connected = False, False
    since = datetime.now(timezone.utc)
    telemetry_due = 0
    account_lock, failed = None, False
    try:
        while not stop.is_set():
            client = client_by_id(client_id)
            if client is None:
                raise SafetyStop("Client record was removed or archived.")
            if client.status != "ACTIVE":
                since = datetime.now(timezone.utc)
                stop.wait(2)
                continue
            if client.execution_mode != "HOSTED":
                raise SafetyStop("Client execution mode is no longer HOSTED.")
            access = subscription_access(client_id)
            if not access["allowed"]:
                since = datetime.now(timezone.utc)
                stop.wait(2)
                continue
            try:
                if not connected:
                    hosted, info = connect_mt5(client_id, reconnect=ever_connected)
                    if account_lock is None:
                        account_lock = _acquire_account_lock(hosted)
                    since = datetime.now(timezone.utc)  # No reconnect backlog.
                    connected, ever_connected = True, True
                    if retries.recovered():
                        _notify(client_id, "AZT MT5 recovered. Waiting for fresh signals.", f"hosted-recovered:{client_id}:{since.isoformat()}")
                    set_hosted_account_status(client_id, "ACTIVE")
                info = verify_hosted_account(hosted)
            except TemporaryConnectionError as exc:
                connected = False
                mt5.shutdown()
                clocks.clear()
                from broker.clock import _clocks
                _clocks.clear()
                delay = retries.failed()
                set_hosted_runtime(client_id, last_error=f"{retries.state}: {exc}; retry in {delay:g}s", last_seen_utc=utc_now())
                if retries.should_alert():
                    _notify(client_id, "AZT MT5 connection degraded; automatic reconnect continues.", f"hosted-disconnected:{client_id}:{time.time()}")
                stop.wait(delay)
                continue
            set_hosted_runtime(
                client_id,
                last_error="",
                last_seen_utc=utc_now(),
                account_balance=float(info.balance),
                account_equity=float(info.equity),
            )
            key = f"{hosted['mt5_server']}|{hosted['mt5_login']}"
            if time.monotonic() >= telemetry_due:
                _capture_hosted(client_id, key, clocks)
                telemetry_due = time.monotonic() + 10
            row = next_instruction(client_id)
            if row is None:
                stop.wait(2)
                continue
            payload = json.loads(str(row["payload_json"]))
            if str(payload.get("kind", "")).upper() != "TEST":
                created = datetime.fromisoformat(str(row["created_utc"]).replace("Z", "+00:00"))
                if created < since or not signal_is_fresh(payload):
                    acknowledge_instruction(client_id, int(row["id"]), "SKIPPED", "Signal predates Start/reconnect or is outside its permitted age.")
                    continue
            signal_key = str(row["signal_key"])
            if not claim_signal(key, signal_key):
                acknowledge_instruction(client_id, int(row["id"]), "SKIPPED", "Durable execution claim already exists; no repeat submission.")
                continue
            try:
                if str(payload.get("kind", "")).upper() == "TEST":
                    ack_status = "TEST_OK"
                    ack_message = str(
                        payload.get("message", "Hosted remote link test received.")
                    )
                else:
                    policy = effective_risk_policy(client)
                    def guard():
                        verify_hosted_account(hosted)
                        current = client_by_id(client_id)
                        if stop.is_set() or current is None or current.status != "ACTIVE" or current.execution_mode != "HOSTED":
                            raise SafetyStop("Hosted execution stopped before order submission.")
                        if not subscription_access(client_id)["allowed"] or news_lock_enabled():
                            raise SafetyStop("Subscription or News Lock blocks new entries.")
                        latest = effective_risk_policy(current)
                        if any(latest.get(field) != policy.get(field) for field in ("risk_per_trade_pct", "max_open_risk_pct", "max_daily_loss_pct", "daily_profit_target_enabled", "daily_profit_target_pct")):
                            raise SafetyStop("Risk policy changed before hosted order submission.")
                        if stop.is_set():
                            raise SafetyStop("Hosted execution stopped before order submission.")
                        verify_hosted_account(hosted)
                        if not signal_is_fresh(payload):
                            raise SafetyStop("Signal expired before order submission.")
                    result = execute_instruction(
                        payload,
                        policy["risk_per_trade_pct"],
                        policy["max_open_risk_pct"],
                        policy["max_daily_loss_pct"],
                        policy["daily_profit_target_enabled"],
                        policy["daily_profit_target_pct"],
                        before_send=guard,
                        strict_history=True,
                    )
                    ack_status = "EXECUTED" if result.sent else "REJECTED"
                    ack_message = (
                        f"{result.message} | ticket={result.ticket or '-'} "
                        f"| volume={result.volume} "
                        f"| risk={result.planned_risk_pct:.3f}% "
                        f"| portfolio_after={result.portfolio_after_pct:.3f}%"
                    )
                    if result.sent:
                        try:
                            from .trade_telemetry import record_execution
                            from .store import DB_PATH
                            record_execution(client_id, key, result.ticket, payload, risk_pct=result.planned_risk_pct, database=DB_PATH)
                        except Exception as exc:
                            logging.warning("Hosted execution metadata unavailable (%s).", type(exc).__name__)
            except Exception as exc:
                ack_status = "ERROR_REVIEW"
                ack_message = f"HOSTED_EXECUTION_REVIEW: {exc}"
            _finish_claim(key, signal_key, ack_status, ack_message)
            acknowledge_instruction(
                client_id,
                int(row["id"]),
                ack_status,
                ack_message,
            )

    except Exception as exc:
        failed = True
        set_hosted_runtime(
            client_id,
            worker_pid=None,
            last_error=str(exc),
            last_seen_utc=utc_now(),
        )
        try:
            set_hosted_account_status(client_id, "FAILED")
        except Exception:
            pass
        raise
    finally:
        mt5.shutdown()
        if account_lock is not None:
            account_lock.close()
        if not failed:
            try:
                set_hosted_runtime(client_id, worker_pid=None, last_error="", last_seen_utc=utc_now())
                set_hosted_account_status(client_id, "PROVISIONED")
            except Exception as exc:
                logging.warning("Hosted shutdown status unavailable (%s).", type(exc).__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-id", type=int, required=True)
    args = parser.parse_args()
    run(args.client_id)


if __name__ == "__main__":
    main()
