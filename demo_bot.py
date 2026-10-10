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
from broker.m15_trailing import M15StructureTrailingManager
from broker.mt5_client import MT5Client
from config import (
    ACTIVE_MARKETS,
    DEMO_MAGIC,
    DEMO_MAX_SIGNAL_AGE_MINUTES,
    DEMO_POLL_SECONDS,
    DEMO_RISK_PCT,
    M5_BARS,
    MIN_STOP_ATR,
    MAX_TOTAL_OPEN_RISK_PCT,
    M15_TRAILING_ENABLED,
    M15_TRAIL_ACTIVATE_R,
    M15_TRAIL_SWING_SPAN,
    M15_TRAIL_ATR_BUFFER,
    M15_TRAIL_LOOKBACK_BARS,
    REPORTS_DIR,
)
from strategies import StrategyRegistry
from telegram import TelegramController


def _setup_epoch(signal) -> float:
    value = str(signal.setup_time).replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _signal_key(market: str, signal) -> str:
    return f"{market}|{signal.strategy_id}|{signal.direction}|{signal.setup_time}"


def _log(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str, separators=(",", ":")) + "\n")


def _load_executed(path: Path) -> set[str]:
    """Restore signal keys written by the current multi-market journal format."""
    seen: set[str] = set()
    if not path.exists():
        return seen
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    market = str(row.get("market", "")).strip()
                    signal = row.get("signal") or {}
                    if not market or not signal:
                        continue
                    seen.add(
                        f"{market}|{signal.get('strategy_id')}|"
                        f"{signal.get('direction')}|{signal.get('setup_time')}"
                    )
                except Exception:
                    continue
    except Exception:
        pass
    return seen


def _bot_positions() -> dict[int, object]:
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


def _build_market_stack() -> tuple[dict, object]:
    """Connect all configured markets to the same logged-in MT5 terminal."""
    clients = {}
    status = None
    for market, hint in ACTIVE_MARKETS.items():
        client = MT5Client(hint)
        status = client.connect()
        clients[market] = client
    return clients, status


def main() -> None:
    load_dotenv()
    orders_log = Path(REPORTS_DIR) / "demo_orders.jsonl"
    executed = _load_executed(orders_log)
    telegram_trade_messages: dict[int, int] = {}

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_admin_raw = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
    tg_admin = int(tg_admin_raw) if tg_admin_raw.isdigit() else 0
    telegram = TelegramController(tg_token, tg_admin)

    clients: dict[str, MT5Client] = {}

    try:
        clients, _ = _build_market_stack()
        primary_symbol = next(iter(clients.values())).symbol
        guard = DemoExecutor(primary_symbol, DEMO_RISK_PCT, DEMO_MAGIC, MAX_TOTAL_OPEN_RISK_PCT)
        account = guard.assert_demo_account()

        registries = {
            market: StrategyRegistry(market=market, min_stop_atr=MIN_STOP_ATR)
            for market in clients
        }
        executors = {
            market: DemoExecutor(
                client.symbol,
                DEMO_RISK_PCT,
                DEMO_MAGIC,
                MAX_TOTAL_OPEN_RISK_PCT,
            )
            for market, client in clients.items()
        }

        trailing = M15StructureTrailingManager(
            magic=DEMO_MAGIC,
            activation_r=M15_TRAIL_ACTIVATE_R,
            swing_span=M15_TRAIL_SWING_SPAN,
            atr_buffer=M15_TRAIL_ATR_BUFFER,
            lookback_bars=M15_TRAIL_LOOKBACK_BARS,
        )

        previous_positions = _bot_positions()
        market_text = ", ".join(f"{m}={c.symbol}" for m, c in clients.items())
        strategy_text = "; ".join(
            f"{m}: {', '.join(registries[m].strategy_ids)}"
            for m in clients
        )

        telegram.update_snapshot(
            status={
                "account": f"{account['login']} @ {account['server']}",
                "symbol": market_text,
                "balance": f"{account['balance']:.2f} {account['currency']}",
                "equity": f"{account['equity']:.2f} {account['currency']}",
                "positions": len(previous_positions),
            },
            positions_text=_positions_text(previous_positions),
        )
        telegram.start()

        print("GOLD_AI MULTI-MARKET DEMO TRADER")
        print(f"ACCOUNT       : {account['login']} @ {account['server']}")
        print("ACCOUNT TYPE  : DEMO")
        print("REAL ACCOUNT  : HARD-BLOCKED")
        print(f"MARKETS       : {market_text}")
        print("TIMEFRAME     : M5")
        print(f"RISK / TRADE  : STRICT {DEMO_RISK_PCT}% of current equity")
        print(f"STRATEGIES    : {strategy_text}")
        print(f"STOP FLOOR    : {MIN_STOP_ATR} ATR where refined strategy requires it")
        print("DAILY CAPS    : DISABLED")
        print(f"OPEN RISK CAP : {MAX_TOTAL_OPEN_RISK_PCT}% across all GOLD_AI positions")
        print(
            "M15 TRAILING  : "
            + (
                f"ON after {M15_TRAIL_ACTIVATE_R}R; M5 swing span={M15_TRAIL_SWING_SPAN}; "
                f"buffer={M15_TRAIL_ATR_BUFFER} ATR"
                if M15_TRAILING_ENABLED else "OFF"
            )
        )
        print("AI MODE       : SHADOW / NOT REQUIRED FOR EXECUTION")
        print("CONCURRENCY   : RISK-BASED (no simple trade-count cap)")
        print("OPPOSITE SIDE : ALLOWED IF THE MT5 ACCOUNT SUPPORTS HEDGING")
        print(f"POLLING       : every {DEMO_POLL_SECONDS}s")
        print(f"TELEGRAM      : {'ENABLED' if telegram.configured else 'DISABLED - env vars missing'}")
        print(f"DEDUP RESTORE : {len(executed)} persisted signal keys")
        print("STATUS        : RUNNING - Ctrl+C to stop")

        if telegram.configured:
            telegram.notify(
                "🤖 GOLD_AI — ONLINE\n\n"
                f"Account: Demo • {account['login']}\n"
                f"Broker: {account['server']}\n"
                f"Markets: {market_text}\n"
                f"Risk: STRICT {DEMO_RISK_PCT}% per trade\n"
                "Daily caps: OFF\n"
                f"Max total open risk: {MAX_TOTAL_OPEN_RISK_PCT}%\n"
                f"Strategies: {strategy_text}\n"
                f"Open GOLD_AI positions: {len(previous_positions)}\n\n"
                "Commands: /status • /positions • /pause"
            )
            if previous_positions:
                telegram.notify(
                    "🔄 EXISTING POSITIONS DETECTED\n\n"
                    "These positions were already open when this runtime started.\n\n"
                    + _positions_text(previous_positions)
                )

        while not telegram.state.stop_requested:
            try:
                now = datetime.now(timezone.utc).timestamp()

                if not telegram.state.paused:
                    for market, client in clients.items():
                        candles = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
                        signals = registries[market].scan(candles)
                        executor = executors[market]

                        for signal in signals:
                            key = _signal_key(market, signal)
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
                                "market": market,
                                "symbol": client.symbol,
                                "signal_key": key,
                                "signal": asdict(signal),
                                "result": asdict(result),
                            }
                            _log(orders_log, row)

                            label = "SENT" if result.sent else "SKIPPED"
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] {label} "
                                f"{market}/{client.symbol} {signal.strategy_id} {signal.direction} "
                                f"vol={result.volume} planned_risk={result.planned_risk_cash:.2f} "
                                f"({result.planned_risk_pct:.3f}%) portfolio_after="
                                f"{result.portfolio_post_trade_risk_pct:.3f}% price={result.price} "
                                f"SL={result.stop_loss} TP={result.take_profit} {result.message}"
                            )

                            journal = (
                                f"{label} | {market} {signal.strategy_id} {signal.direction} | "
                                f"vol {result.volume} | risk {result.planned_risk_pct:.3f}% | "
                                f"portfolio {result.portfolio_post_trade_risk_pct:.3f}% | "
                                f"entry {result.price} | SL {result.stop_loss} | TP {result.take_profit}"
                            )
                            telegram.update_snapshot(journal_text=journal)

                            if result.sent:
                                side_icon = "🟢" if signal.direction == "BUY" else "🔴"
                                message_id = telegram.notify(
                                    "🚀 GOLD_AI — NEW TRADE\n\n"
                                    f"Market: {market}\n"
                                    f"Strategy: {signal.strategy_id}\n"
                                    f"{side_icon} {signal.direction} {client.symbol}\n"
                                    f"Size: {result.volume} lot\n\n"
                                    f"Entry: {_fmt_price(result.price)}\n"
                                    f"SL:    {_fmt_price(result.stop_loss)}\n"
                                    f"TP:    {_fmt_price(result.take_profit)}\n\n"
                                    f"Planned risk: {result.planned_risk_pct:.3f}% "
                                    f"(~{result.planned_risk_cash:.2f})\n"
                                    f"Portfolio after entry: {result.portfolio_post_trade_risk_pct:.3f}% "
                                    f"/ {MAX_TOTAL_OPEN_RISK_PCT:.3f}%"
                                )
                                if result.ticket and message_id:
                                    telegram_trade_messages[int(result.ticket)] = int(message_id)
                            elif telegram.configured:
                                telegram.notify(
                                    "⚠️ ORDER NOT OPENED\n"
                                    f"{market} • {signal.strategy_id} • {signal.direction}\n"
                                    f"{result.message}"
                                )

                if M15_TRAILING_ENABLED:
                    for trail in trailing.update_all():
                        if trail.changed:
                            trail_text = (
                                f"🔒 TRAILING SL UPDATED\n"
                                f"Ticket #{trail.ticket}\n"
                                f"SL: {_fmt_price(trail.old_sl)} → {_fmt_price(trail.new_sl)}"
                            )
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] TRAIL "
                                f"ticket={trail.ticket} SL={trail.old_sl} -> {trail.new_sl}"
                            )
                            telegram.update_snapshot(journal_text=trail_text.replace("\n", " | "))
                            if telegram.configured:
                                telegram.notify(trail_text)

                current_positions = _bot_positions()
                for ticket, old_position in previous_positions.items():
                    if ticket not in current_positions:
                        reason, pnl, exit_price = _closed_position_event(ticket, old_position)
                        if reason == "TP":
                            summary = f"✅ TP HIT • {old_position.symbol} • {pnl:+.2f}"
                        elif reason == "SL":
                            summary = f"❌ SL HIT • {old_position.symbol} • {pnl:+.2f}"
                        else:
                            summary = f"🏁 TRADE CLOSED • {old_position.symbol} • {pnl:+.2f}"
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
                        "symbol": market_text,
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
        MT5Client.shutdown()


if __name__ == "__main__":
    main()
