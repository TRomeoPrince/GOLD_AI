"""Separate, explicitly opt-in Headway REAL runner. Never modifies demo_bot.py."""
from __future__ import annotations

import argparse
import json
import msvcrt
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
from dotenv import load_dotenv

from broker.headway_live_executor import HeadwayLiveExecutor
from broker.mt5_client import MT5Client
from config import DATA_DIR, M5_BARS, REPORTS_DIR, SYMBOL_HINT
from demo_bot import _closed_position_event, _fmt_price, _log, _positions_text, _setup_epoch, _signal_key
from strategies import StrategyRegistry
from telegram import TelegramController

MAGIC = 560091
POLL_SECONDS = 5
MAX_SIGNAL_AGE_MINUTES = 10
MAX_DAILY_REALIZED_LOSS_USD = 5.0


def _account_positions() -> dict[int, object]:
    positions = mt5.positions_get()
    if positions is None:
        raise RuntimeError(f"Cannot read open positions: {mt5.last_error()}")
    return {
        int(p.ticket): p for p in positions
        if int(getattr(p, "magic", -1)) == MAGIC
    }


def _seen_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    result = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("key"):
                result.add(row["key"])
        except (ValueError, TypeError):
            continue
    return result


def _record_key(path: Path, key: str) -> None:
    # Write BEFORE order_send. Crash after this point skips rather than duplicates.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "at": datetime.now(timezone.utc).isoformat()}) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _daily_realized_pnl() -> float:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(midnight, now)
    if deals is None:
        raise RuntimeError(f"Cannot verify today's realized P/L: {mt5.last_error()}")
    return sum(
        float(getattr(d, "profit", 0.0))
        + float(getattr(d, "commission", 0.0))
        + float(getattr(d, "swap", 0.0))
        + float(getattr(d, "fee", 0.0))
        for d in deals
        if int(getattr(d, "magic", -1)) == MAGIC
    )


def _single_instance(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = lock_path.open("a+b")
    f.seek(0, os.SEEK_END)
    if f.tell() == 0:
        f.write(b"0")
        f.flush()
    f.seek(0)
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        raise RuntimeError("Another Headway live runner already holds the account lock.")
    return f


def _save_message_map(path: Path, mapping: dict[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({str(k): v for k, v in mapping.items()}), encoding="utf-8")
    tmp.replace(path)


def _load_message_map(path: Path) -> dict[int, int]:
    if not path.exists():
        return {}
    return {int(k): int(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="GOLD_AI Headway REAL runner")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Read-only connection and signal check")
    mode.add_argument("--live", action="store_true", help="Opt into REAL orders (requires account env confirmation)")
    args = parser.parse_args()
    load_dotenv()
    authorized_raw = os.getenv("HEADWAY_LIVE_ACCOUNT", "").strip()
    if args.live and (not authorized_raw.isdigit() or os.getenv("HEADWAY_LIVE_ENABLED", "") != "YES"):
        raise SystemExit(
            "LIVE BLOCKED. Set HEADWAY_LIVE_ACCOUNT to the exact MT5 login and "
            "HEADWAY_LIVE_ENABLED=YES, then pass --live."
        )
    client = MT5Client(SYMBOL_HINT)
    telegram = None
    lock = None
    try:
        client.connect()
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("MT5 account unavailable.")
        print("GOLD_AI — HEADWAY REAL ACCOUNT")
        print(f"MT5 login : {account.login}")
        print(f"Server    : {account.server}")
        print(f"Currency  : {account.currency}")
        print(f"Equity    : {account.equity:.2f}")
        print(f"Symbol    : {client.symbol}")
        print(f"Mode      : {'LIVE ORDERS' if args.live else 'CHECK ONLY / NO ORDERS'}")
        if args.check:
            if "headway" not in str(account.server).lower():
                print("WARNING: This is not a Headway server.")
            if int(account.trade_mode) != int(mt5.ACCOUNT_TRADE_MODE_REAL):
                print("WARNING: This is not a real MT5 account.")
            info = mt5.symbol_info(client.symbol)
            print(f"Minimum lot: {info.volume_min if info else 'unknown'}")
            signals = StrategyRegistry().scan(client.candles(mt5.TIMEFRAME_M5, M5_BARS))
            print(f"Current signals: {len(signals)}")
            for s in signals:
                print(f"  {s.strategy_id} {s.direction} entry={s.entry} SL={s.stop_loss} TP={s.take_profit}")
            print("NO ORDERS SENT.")
            return

        executor = HeadwayLiveExecutor(client.symbol, MAGIC, int(authorized_raw))
        verified = executor.assert_demo_account()
        lock = _single_instance(Path(DATA_DIR) / f"headway_{verified['login']}.lock")
        ledger = Path(DATA_DIR) / f"headway_{verified['login']}_signal_ledger.jsonl"
        message_map_path = Path(DATA_DIR) / f"headway_{verified['login']}_telegram_map.json"
        orders_log = Path(REPORTS_DIR) / "headway_live_orders.jsonl"
        seen = _seen_keys(ledger)
        message_map = _load_message_map(message_map_path)
        registry = StrategyRegistry()
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        admin_raw = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
        telegram = TelegramController(token, int(admin_raw) if admin_raw.isdigit() else 0)
        previous = _account_positions()
        telegram.update_snapshot(
            status={"account": f"{account.login} @ {account.server}", "symbol": client.symbol,
                    "balance": f"{account.balance:.2f} USD", "equity": f"{account.equity:.2f} USD",
                    "positions": len(previous)},
            positions_text=_positions_text(previous),
        )
        telegram.start()
        telegram.notify(
            f"🟠 GOLD_AI — HEADWAY REAL TEST\nAccount: {account.login}\n"
            f"Symbol: {client.symbol} • M5\nFixed volume: broker minimum\n"
            "Planned risk ceiling: $5 or 50% of equity, whichever is lower\n"
            "Max open positions: 1 across the account\n"
            "Commands: /status • /positions • /pause • /stop"
        )
        print(f"Strategies: {', '.join(registry.strategy_ids)}")
        print("Risk ceiling: min($5, 50% of equity), with 10% loss-estimate buffer")
        print("Volume: broker minimum only; technical SL/TP unchanged")
        print("Max positions: 1 account-wide; pending orders block new entries")
        print("Daily realized loss stop: $5 (bot trades)")
        print(f"Restored signal keys: {len(seen)}")
        print("Ctrl+C or Telegram /stop ends runner; open MT5 positions stay open.")

        while not telegram.state.stop_requested:
            try:
                executor.assert_demo_account()  # recheck login/server on every poll
                candles = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
                signals = registry.scan(candles)
                now = datetime.now(timezone.utc).timestamp()
                if not telegram.state.paused:
                    for signal in signals:
                        key = f"{verified['login']}|{client.symbol}|{_signal_key(signal)}"
                        if key in seen:
                            continue
                        age = max(0.0, (now - _setup_epoch(signal)) / 60.0)
                        if age > MAX_SIGNAL_AGE_MINUTES:
                            continue
                        _record_key(ledger, key)
                        seen.add(key)
                        if _daily_realized_pnl() <= -MAX_DAILY_REALIZED_LOSS_USD:
                            print("[DAILY LOSS STOP] No further orders today.")
                            break
                        result = executor.send(signal)
                        _log(orders_log, {
                            "time_utc": datetime.now(timezone.utc).isoformat(),
                            "account": verified["login"],
                            "signal": asdict(signal),
                            "result": asdict(result),
                        })
                        label = "SENT" if result.sent else "SKIPPED"
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] {label} "
                              f"{signal.strategy_id} {signal.direction}: {result.message}")
                        telegram.update_snapshot(journal_text=f"{label} | {signal.strategy_id} {signal.direction} | {result.message}")
                        if result.sent:
                            msg_id = telegram.notify(
                                "🚀 GOLD_AI — HEADWAY REAL TRADE\n\n"
                                f"Strategy: {signal.strategy_id}\n"
                                f"{signal.direction} {client.symbol}\n"
                                f"Size: {result.volume} lot\n"
                                f"Entry: {_fmt_price(result.price)}\n"
                                f"SL: {_fmt_price(result.stop_loss)}\n"
                                f"TP: {_fmt_price(result.take_profit)}"
                            )
                            if result.ticket and msg_id:
                                message_map[int(result.ticket)] = int(msg_id)
                                _save_message_map(message_map_path, message_map)

                current = _account_positions()
                for ticket, old_position in previous.items():
                    if ticket not in current:
                        reason, pnl, _ = _closed_position_event(ticket, old_position)
                        icon = "✅" if reason == "TP" else ("❌" if reason == "SL" else "🏁")
                        text = f"{icon} {reason} • {pnl:+.2f} USD"
                        telegram.update_snapshot(journal_text=text)
                        telegram.notify(text, reply_to_message_id=message_map.get(ticket))
                        message_map.pop(ticket, None)
                        _save_message_map(message_map_path, message_map)
                previous = current
                account_now = mt5.account_info()
                telegram.update_snapshot(
                    status={"account": f"{account_now.login} @ {account_now.server}",
                            "symbol": client.symbol,
                            "balance": f"{account_now.balance:.2f} USD",
                            "equity": f"{account_now.equity:.2f} USD",
                            "positions": len(current)},
                    positions_text=_positions_text(current),
                )
                time.sleep(POLL_SECONDS)
            except KeyboardInterrupt:
                print("Headway runner stopped by user.")
                break
            except Exception as exc:
                print(f"[HEADWAY ERROR] {exc}")
                telegram.notify(f"⚠️ GOLD_AI HEADWAY ERROR\n{exc}")
                # Authorization failures must stop, not retry on a different account.
                if "LIVE BLOCKED" in str(exc):
                    break
                time.sleep(POLL_SECONDS)
    finally:
        if telegram is not None:
            telegram.notify("🔴 GOLD_AI HEADWAY STOPPED\nExisting broker SL/TP orders remain active.")
            telegram.stop()
        if lock is not None:
            lock.close()
        client.shutdown()


if __name__ == "__main__":
    main()
