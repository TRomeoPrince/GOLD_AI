from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone

import MetaTrader5 as mt5

from broker.mt5_client import MT5Client
from config import ACTIVE_MARKETS, DEMO_MAX_SIGNAL_AGE_MINUTES, DEMO_POLL_SECONDS, M5_BARS
from strategies import StrategyRegistry

from .store import active_clients, enqueue_instruction


def _setup_epoch(signal) -> float:
    value = str(signal.setup_time).replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _signal_key(market: str, signal) -> str:
    return f"{market}|{signal.strategy_id}|{signal.direction}|{signal.setup_time}"


def main() -> None:
    clients = {}
    for market, hint in ACTIVE_MARKETS.items():
        mt5_client = MT5Client(hint)
        mt5_client.connect()
        clients[market] = mt5_client

    registries = {
        market: StrategyRegistry(market=market)
        for market in clients
    }

    seen: set[str] = set()
    print("GOLD_AI OWNER SIGNAL ENGINE")
    print("Protected strategies run here; customer clients receive instructions only.")
    print("Ctrl+C to stop.")

    while True:
        now = datetime.now(timezone.utc).timestamp()
        for market, client in clients.items():
            candles = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
            signals = registries[market].scan(candles)

            for signal in signals:
                key = _signal_key(market, signal)
                if key in seen:
                    continue

                age_minutes = max(0.0, (now - _setup_epoch(signal)) / 60.0)
                if age_minutes > DEMO_MAX_SIGNAL_AGE_MINUTES:
                    seen.add(key)
                    continue

                payload = {
                    "market": market,
                    "symbol_hint": client.symbol,
                    "strategy_id": signal.strategy_id,
                    "direction": signal.direction,
                    "setup_time": str(signal.setup_time),
                    "stop_loss": float(signal.stop_loss),
                    "take_profit": float(signal.take_profit),
                    "metadata": asdict(signal),
                }
                encoded = json.dumps(payload, default=str, separators=(",", ":"))

                queued = 0
                for customer in active_clients():
                    if enqueue_instruction(customer.id, key, encoded):
                        queued += 1

                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"{market} {signal.strategy_id} {signal.direction} "
                    f"queued_for={queued}"
                )
                seen.add(key)

        time.sleep(DEMO_POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    finally:
        mt5.shutdown()
