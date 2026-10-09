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
from telegram import TelegramController


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


def _gold_positions() -> dict[int, object]:
    positions = mt5.positions_get() or ()
    return {
        int(p.ticket): p
        for p in positions
        if int(getattr(p, "magic", -1)) == DEMO_MAGIC
    }


def _positions_text(positions: dict[int, object]) -> str:
    if not positions:
        return "📊 GOLD_AI — OPEN POSITIONS\n\nNo open GOLD_AI positions."
    lines = [f"📊 GOLD_AI — OPEN POSITIONS ({len(positions)})"]
    total = 0.0
    for index, p in enumerate(positions.values(), 1):
        side = "🟢 BUY" if int(p.type) == int(mt5.POSITION_TYPE_BUY) else "🔴 SELL"
        pnl = float(p.profit)
        total += pnl
        lines.extend([
            "",
            f"{index}. {side} {p.symbol} • {p.volume} lot",
            f"Entry   {p.price_open}",
            f"Current {p.price_current}",
            f"SL      {p.sl}",
            f"TP      {p.tp}",
            f"P/L     {pnl:+.2f}",
            f"Ticket  #{p.ticket}",
        ])
    lines.extend(["", f"Floating P/L: {total:+.2f}"])
    return "\n".join(lines)


def _fmt_price(value: object) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _closed_position_event(ticket: int, old_position: object) -> tuple[str, float, object]:

    deals = mt5.history_deals_get(position=ticket) or ()
    exit_deals = [
        d for d in deals
        if int(getattr(d, "entry", -1)) in {
            int(getattr(mt5, "DEAL_ENTRY_OUT", 1)),
            int(getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)),
        }
    ]
    side = "BUY" if int(old_position.type) == int(mt5.POSITION_TYPE_BUY) else "SELL"
    if not exit_deals:
        return "CLOSED", 0.0, "-"
    pnl = sum(
        float(getattr(d, "profit", 0.0))
        + float(getattr(d, "commission", 0.0))
        + float(getattr(d, "swap", 0.0))
        + float(getattr(d, "fee", 0.0))
        for d in exit_deals
    )
    last = exit_deals[-1]
    reason = {
        int(getattr(mt5, "DEAL_REASON_SL", 4)): "SL",
        int(getattr(mt5, "DEAL_REASON_TP", 5)): "TP",
    }.get(int(getattr(last, "reason", -1)), "EXIT")
    return reason, pnl, getattr(last, "price", "-")


def main() -> None:
    load_dotenv()
    client = MT5Client(SYMBOL_HINT)
    registry = StrategyRegistry()
    executed: set[str] = set()
    orders_log = Path(REPORTS_DIR) / "demo_orders.jsonl"
    telegram_trade_messages: dict[int, int] = {}

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_admin_raw = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
    tg_admin = int(tg_admin_raw) if tg_admin_raw.isdigit() else 0
    telegram = TelegramController(tg_token, tg_admin)

    try:
        status = client.connect()
        executor = DemoExecutor(client.symbol, DEMO_RISK_PCT, DEMO_MAGIC)
        account = executor.assert_demo_account()
        previous_positions = _gold_positions()

        telegram.update_snapshot(
            status={
                "account": f"{account['login']} @ {account['server']}",
                "symbol": client.symbol,
                "balance": f"{account['balance']:.2f} {account['currency']}",
                "equity": f"{account['equity']:.2f} {account['currency']}",
                "positions": len(previous_positions),
            },
            positions_text=_positions_text(previous_positions),
        )
        telegram.start()

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
        print(f"TELEGRAM      : {'ENABLED' if telegram.configured else 'DISABLED - env vars missing'}")
        print("STATUS        : RUNNING - Ctrl+C to stop")

        if telegram.configured:
            telegram.notify(
                "🤖 GOLD_AI — ONLINE\n\n"
                f"Account: Demo • {account['login']}\n"
                f"Broker: {account['server']}\n"
                f"Market: {client.symbol} • M5\n"
                f"Risk: {DEMO_RISK_PCT}% per trade\n"
                "AI: SHADOW\n"
                f"Open GOLD_AI positions: {len(previous_positions)}\n\n"
                "Commands: /status • /positions • /pause"
            )
            if previous_positions:
                telegram.notify(
                    "🔄 EXISTING POSITIONS DETECTED\n\n"
                    "These positions were already open when this runtime started. "
                    "They were not opened by this Telegram session.\n\n"
                    + _positions_text(previous_positions)
                )

        while not telegram.state.stop_requested:
            try:
                candles = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
                signals = registry.scan(candles)
                now = datetime.now(timezone.utc).timestamp()

                # /pause blocks new entries only. Existing positions retain
                # broker-side SL/TP and continue to be monitored/journaled.
                if not telegram.state.paused:
                    for signal in signals:
                        key = _signal_key(signal)
                        if key in executed:
                            continue

                        age_minutes = max(0.0, (now - _setup_epoch(signal)) / 60.0)
                        if age_minutes > DEMO_MAX_SIGNAL_AGE_MINUTES:
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

                        journal = (
                            f"{label} | {signal.strategy_id} {signal.direction} | "
                            f"vol {result.volume} | entry {result.price} | "
                            f"SL {result.stop_loss} | TP {result.take_profit}"
                        )
                        telegram.update_snapshot(journal_text=journal)
                        if result.sent:
                            side_icon = "🟢" if signal.direction == "BUY" else "🔴"
                            risk_cash = (float(mt5.account_info().equity) * DEMO_RISK_PCT / 100.0) if mt5.account_info() else 0.0
                            message_id = telegram.notify(
                                "🚀 GOLD_AI — NEW TRADE\n\n"
                                f"Strategy: {signal.strategy_id}\n"
                                f"{side_icon} {signal.direction} {client.symbol}\n"
                                f"Size: {result.volume} lot\n\n"
                                f"Entry: {_fmt_price(result.price)}\n"
                                f"SL:    {_fmt_price(result.stop_loss)}\n"
                                f"TP:    {_fmt_price(result.take_profit)}\n\n"
                                f"Risk target: {DEMO_RISK_PCT}% (~{risk_cash:.2f})"
                            )
                            if result.ticket and message_id:
                                telegram_trade_messages[int(result.ticket)] = int(message_id)
                        elif telegram.configured:
                            telegram.notify(
                                "⚠️ ORDER NOT OPENED\n"
                                f"{signal.strategy_id} | {signal.direction}\n{result.message}"
                            )

                current_positions = _gold_positions()
                for ticket, old_position in previous_positions.items():
                    if ticket not in current_positions:
                        reason, pnl, exit_price = _closed_position_event(ticket, old_position)
                        if reason == "TP":
                            summary = f"✅ TP HIT • {pnl:+.2f}"
                        elif reason == "SL":
                            summary = f"❌ SL HIT • {pnl:+.2f}"
                        else:
                            summary = f"🏁 TRADE CLOSED • {pnl:+.2f}"
                        telegram.update_snapshot(journal_text=summary)
                        telegram.notify(
                            summary,
                            reply_to_message_id=telegram_trade_messages.get(ticket),
                        )
                        telegram_trade_messages.pop(ticket, None)

                account_now = mt5.account_info()
                telegram.update_snapshot(
                    status={
                        "account": f"{account_now.login} @ {account_now.server}" if account_now else "-",
                        "symbol": client.symbol,
                        "balance": f"{account_now.balance:.2f} {account_now.currency}" if account_now else "-",
                        "equity": f"{account_now.equity:.2f} {account_now.currency}" if account_now else "-",
                        "positions": len(current_positions),
                    },
                    positions_text=_positions_text(current_positions),
                )
                previous_positions = current_positions
                time.sleep(DEMO_POLL_SECONDS)

            except KeyboardInterrupt:
                print("\nGOLD_AI demo trader stopped by user.")
                break
            except Exception as exc:
                print(f"[LOOP ERROR] {exc}")
                telegram.notify(f"⚠️ GOLD_AI LOOP ERROR\n{exc}")
                time.sleep(max(DEMO_POLL_SECONDS, 5))

    finally:
        if telegram.configured:
            telegram.notify(
                "🔴 GOLD_AI STOPPED\n"
                "The runtime has stopped. This command/process does not close existing MT5 positions."
            )
        telegram.stop()
        client.shutdown()


if __name__ == "__main__":
    main()
