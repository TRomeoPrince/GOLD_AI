from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5

from broker.mt5_client import MT5Client
from config import ACTIVE_MARKETS, DEMO_MAX_SIGNAL_AGE_MINUTES, DEMO_POLL_SECONDS, M5_BARS
from strategies import StrategyRegistry

from .personal_store import publish_signal, write_status
from .store import active_clients, enqueue_instruction, news_lock_enabled
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


def main(stop=None) -> None:
    import threading
    stop = stop or threading.Event()
    write_status("signal_engine", state="CONNECTING", message="Connecting market data to MT5")
    print("Connecting signal engine market data to MT5...", flush=True)
    clients = {}
    retries = RetryState()
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
        write_status("signal_engine", state="NEWS_LOCK" if news_lock_enabled() else "SCANNING", markets=list(clients))
        if news_lock_enabled():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] NEWS LOCK active — new entries blocked.")
            stop.wait(DEMO_POLL_SECONDS)
            continue

        now = datetime.now(timezone.utc).timestamp()
        for market, client in clients.items():
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

                publish_signal(key, payload, legacy_key=legacy_key)
                queued = 0
                for customer in active_clients():
                    if enqueue_instruction(customer.id, key, encoded, legacy_key=legacy_key):
                        queued += 1

                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"{market} {signal.strategy_id} {signal.direction} "
                    f"queued_for={queued}"
                )
                seen.add(key)

        if connected:
            if retries.recovered():
                write_status("signal_engine", state="RECOVERED", message="Market data recovered; scanning fresh setups.")
            stop.wait(DEMO_POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    finally:
        mt5.shutdown()
