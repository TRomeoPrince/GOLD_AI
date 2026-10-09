from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
from dotenv import load_dotenv

from broker.demo_executor import DemoExecutor
from broker.mt5_client import MT5Client
from config import (
    DEMO_MAGIC,
    DEMO_MAX_SIGNAL_AGE_MINUTES,
    DEMO_POLL_SECONDS,
    DEMO_RISK_PCT,
    M5_BARS,
    REPORTS_DIR,
    SYMBOL_HINT,
)
from strategies import StrategyRegistry


def _setup_epoch(signal) -> float:
    value = str(signal.setup_time).replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _signal_key(signal) -> str:
    return f"{signal.strategy_id}|{signal.direction}|{signal.setup_time}"


def _log(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str, separators=(",", ":")) + "\n")


def main() -> None:
    load_dotenv()
    client = MT5Client(SYMBOL_HINT)
    registry = StrategyRegistry()
    executed: set[str] = set()
    orders_log = Path(REPORTS_DIR) / "demo_orders.jsonl"

    try:
        status = client.connect()
        executor = DemoExecutor(client.symbol, DEMO_RISK_PCT, DEMO_MAGIC)
        account = executor.assert_demo_account()

        print("GOLD_AI DEMO TRADER")
        print(f"ACCOUNT       : {account['login']} @ {account['server']}")
        print("ACCOUNT TYPE  : DEMO")
        print("REAL ACCOUNT  : HARD-BLOCKED")
        print(f"SYMBOL        : {client.symbol}")
        print("TIMEFRAME     : M5")
        print(f"RISK / TRADE  : {DEMO_RISK_PCT}% of current equity")
        print(f"STRATEGIES    : {', '.join(registry.strategy_ids)}")
        print("AI MODE       : SHADOW / NOT REQUIRED FOR EXECUTION")
        print("CONCURRENCY   : NO 2-TRADE CAP (paused for current experiment)")
        print("OPPOSITE SIDE : ALLOWED IF THE MT5 ACCOUNT SUPPORTS HEDGING")
        print(f"POLLING       : every {DEMO_POLL_SECONDS}s")
        print("STATUS        : RUNNING - Ctrl+C to stop")

        while True:
            try:
                candles = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
                signals = registry.scan(candles)
                now = datetime.now(timezone.utc).timestamp()

                for signal in signals:
                    key = _signal_key(signal)
                    if key in executed:
                        continue

                    age_minutes = max(0.0, (now - _setup_epoch(signal)) / 60.0)
                    if age_minutes > DEMO_MAX_SIGNAL_AGE_MINUTES:
                        # Mark old setup as seen so it is not reconsidered forever.
                        executed.add(key)
                        continue

                    result = executor.send(signal)
                    executed.add(key)
                    row = {
                        "time_utc": datetime.now(timezone.utc).isoformat(),
                        "signal": asdict(signal),
                        "result": asdict(result),
                    }
                    _log(orders_log, row)

                    label = "SENT" if result.sent else "SKIPPED"
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] {label} "
                        f"{signal.strategy_id} {signal.direction} "
                        f"vol={result.volume} price={result.price} "
                        f"SL={result.stop_loss} TP={result.take_profit} "
                        f"{result.message}"
                    )

                time.sleep(DEMO_POLL_SECONDS)

            except KeyboardInterrupt:
                print("\nGOLD_AI demo trader stopped by user.")
                break
            except Exception as exc:
                print(f"[LOOP ERROR] {exc}")
                time.sleep(max(DEMO_POLL_SECONDS, 5))

    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
