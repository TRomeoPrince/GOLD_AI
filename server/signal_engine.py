from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

from broker.mt5_client import MT5Client
from config import ACTIVE_MARKETS, DEMO_MAX_SIGNAL_AGE_MINUTES, DEMO_POLL_SECONDS, M5_BARS
from strategies import StrategyRegistry

from .personal_store import publish_signal, write_status
from .store import active_clients, enqueue_instruction, entries_blocked as news_lock_enabled
from .reconnect import RetryState


def _setup_epoch(signal) -> float:
    value = str(signal.setup_time).replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _signal_key(market: str, signal) -> str:
    return f"{market}|{signal.strategy_id}|{signal.direction}|{signal.setup_time}"


def _legacy_signal_key(market, signal, offset_seconds):
    if not offset_seconds:
        return None
    broker_label = datetime.fromtimestamp(_setup_epoch(signal), timezone.utc) + timedelta(seconds=offset_seconds)
    return f"{market}|{signal.strategy_id}|{signal.direction}|{broker_label}"


def _wait_for_database(error, retries, stop):
    code = getattr(error, "sqlite_errorcode", 0)
    if (code & 0xFF) not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        raise error
    delay = retries.failed()
    write_status("signal_engine", state=retries.state, desired=True, retry_in=delay,
                 failures=retries.failures, message="Signal database busy; waiting to retry.")
    stop.wait(delay)


def main(stop=None) -> None:
    import threading
    stop = stop or threading.Event()
    write_status("signal_engine", state="CONNECTING", message="Connecting market data to MT5")
    print("Connecting signal engine market data to MT5...", flush=True)
    clients = {}
    retries = RetryState()
    database_retries = RetryState()
    for market, hint in ACTIVE_MARKETS.items():
        clients[market] = MT5Client(hint)

    registries = {
        market: StrategyRegistry(market=market)
        for market in clients
    }

    seen: set[str] = set()
    print("GOLD_AI OWNER SIGNAL ENGINE / AGORA ZION TRADER")
    print("Protected strategies run here; customer clients receive instructions only.")
    print("Ctrl+C to stop.")

    connected = False
    while not stop.is_set():
        if not connected:
            try:
                for client in clients.values():
                    client.connect()
                connected = True
            except Exception as exc:
                delay = retries.failed()
                write_status("signal_engine", state=retries.state, desired=True, retry_in=delay,
                             failures=retries.failures, message=f"Market data unavailable ({type(exc).__name__}); retrying.")
                mt5.shutdown()
                stop.wait(delay)
                continue
        try:
            locked = news_lock_enabled()
        except sqlite3.OperationalError as exc:
            _wait_for_database(exc, database_retries, stop)
            continue
        write_status("signal_engine", state="NEWS_LOCK" if locked else "SCANNING", markets=list(clients))
        if locked:
            database_retries.recovered()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] NEWS LOCK active — new entries blocked.")
            stop.wait(DEMO_POLL_SECONDS)
            continue

        now = datetime.now(timezone.utc).timestamp()
        database_busy = False
        for market, client in clients.items():
            if stop.is_set():
                break
            try:
                candles = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
            except Exception as exc:
                connected = False
                delay = retries.failed()
                write_status("signal_engine", state=retries.state, desired=True, retry_in=delay,
                             message=f"Market data interrupted ({type(exc).__name__}); reconnecting.")
                stop.wait(delay)
                break
            signals = registries[market].scan(candles)

            for signal in signals:
                if stop.is_set():
                    break
                key = _signal_key(market, signal)
                if key in seen:
                    continue

                age_seconds = now - _setup_epoch(signal)
                if age_seconds < -60 or age_seconds > DEMO_MAX_SIGNAL_AGE_MINUTES * 60:
                    seen.add(key)
                    continue

                legacy_key = _legacy_signal_key(market, signal, client.clock.offset_seconds)
                payload = {
                    "market": market,
                    "symbol_hint": market,
                    "strategy_id": signal.strategy_id,
                    "direction": signal.direction,
                    "setup_time": str(signal.setup_time),
                    "stop_loss": float(signal.stop_loss),
                    "take_profit": float(signal.take_profit),
                    "metadata": asdict(signal),
                    "time_basis": "UTC",
                    "broker_clock_offset_seconds": client.clock.offset_seconds,
                }
                encoded = json.dumps(payload, default=str, separators=(",", ":"))

                try:
                    publish_signal(key, payload, legacy_key=legacy_key)
                    queued = sum(enqueue_instruction(customer.id, key, encoded, legacy_key=legacy_key)
                                 for customer in active_clients())
                except sqlite3.OperationalError as exc:
                    # Unique keys make a partial dispatch safe to retry. Only
                    # mark a signal seen after each intended write can finish.
                    _wait_for_database(exc, database_retries, stop)
                    database_busy = True
                    break

                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"{market} {signal.strategy_id} {signal.direction} "
                    f"queued_for={queued}"
                )
                seen.add(key)

            if database_busy:
                break

        if database_busy:
            continue
        database_retries.recovered()
        if connected:
            if retries.recovered():
                write_status("signal_engine", state="RECOVERED", message="Market data recovered; scanning fresh setups.")
            stop.wait(DEMO_POLL_SECONDS)
    write_status("signal_engine", state="STOPPED", desired=False, message="Signal engine stopped.")


if __name__ == "__main__":
    try:
        main()
    finally:
        mt5.shutdown()
