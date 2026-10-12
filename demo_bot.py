from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
from dotenv import load_dotenv

from ai.shadow import AIShadowEvaluator
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
    MAX_TOTAL_OPEN_RISK_PCT,
    SMALL_ACCOUNT_MAX_RISK_PCT,
    M15_TRAILING_ENABLED,
    M15_TRAIL_ACTIVATE_R,
    M15_TRAIL_SWING_SPAN,
    M15_TRAIL_ATR_BUFFER,
    M15_TRAIL_LOOKBACK_BARS,
    ASIAN_START_HOUR,
    ASIAN_END_HOUR,
    LONDON_START_HOUR,
    LONDON_END_HOUR,
    M15_MIN_REWARD_R,
    M15_H1_PIVOT_SPAN,
    M15_STOP_BUFFER_FRACTION,
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

    account = mt5.account_info()
    currency = str(account.currency) if account is not None else ""
    lines = [f"📊 GOLD_AI — OPEN POSITIONS ({len(positions)})"]

    total_floating = 0.0
    total_sl_pnl = 0.0
    total_tp_pnl = 0.0
    sl_known = True
    tp_known = True

    for index, p in enumerate(positions.values(), 1):
        side = "🟢 BUY" if int(p.type) == int(mt5.POSITION_TYPE_BUY) else "🔴 SELL"
        direction = "BUY" if int(p.type) == int(mt5.POSITION_TYPE_BUY) else "SELL"
        pnl = float(p.profit)
        total_floating += pnl

        sl = float(getattr(p, "sl", 0.0) or 0.0)
        tp = float(getattr(p, "tp", 0.0) or 0.0)
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

        sl_pnl = None
        tp_pnl = None
        if sl > 0:
            value = mt5.order_calc_profit(
                order_type, str(p.symbol), float(p.volume), float(p.price_open), sl
            )
            if value is not None:
                sl_pnl = float(value)
                total_sl_pnl += sl_pnl
            else:
                sl_known = False
        else:
            sl_known = False

        if tp > 0:
            value = mt5.order_calc_profit(
                order_type, str(p.symbol), float(p.volume), float(p.price_open), tp
            )
            if value is not None:
                tp_pnl = float(value)
                total_tp_pnl += tp_pnl
            else:
                tp_known = False
        else:
            tp_known = False

        sl_text = (
            f"{_fmt_price(sl)} ({_fmt_money(sl_pnl, currency)})"
            if sl_pnl is not None
            else f"{_fmt_price(sl)} (estimate unavailable)"
        )
        tp_text = (
            f"{_fmt_price(tp)} ({_fmt_money(tp_pnl, currency)})"
            if tp_pnl is not None
            else f"{_fmt_price(tp)} (estimate unavailable)"
        )

        lines.extend([
            "",
            f"{index}. {side} {p.symbol} • {p.volume} lot",
            f"Entry   {_fmt_price(p.price_open)}",
            f"Current {_fmt_price(p.price_current)}",
            f"SL      {sl_text}",
            f"TP      {tp_text}",
            f"P/L     {_fmt_money(pnl, currency)}",
            f"Ticket  #{p.ticket}",
        ])

    lines.extend([
        "",
        f"Floating P/L: {_fmt_money(total_floating, currency)}",
        (
            f"Total at all SLs: {_fmt_money(total_sl_pnl, currency)}"
            if sl_known
            else "Total at all SLs: incomplete — one or more SL estimates unavailable"
        ),
        (
            f"Total at all TPs: {_fmt_money(total_tp_pnl, currency)}"
            if tp_known
            else "Total at all TPs: incomplete — one or more TP estimates unavailable"
        ),
    ])
    return "\n".join(lines)


def _fmt_price(value: object) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_money(value: float, currency: str) -> str:
    currency = (currency or "").upper()
    sign = "+" if value >= 0 else "-"
    amount = abs(float(value))
    if currency == "USD":
        return f"{sign}" + "$" + f"{amount:.2f}"
    return f"{sign}{amount:.2f} {currency}".strip()


def _estimate_trade_pnl(
    symbol: str,
    direction: str,
    volume: float,
    entry: float,
    stop_loss: float,
    take_profit: float,
) -> tuple[float | None, float | None]:
    if volume <= 0:
        return None, None

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    sl_pnl = mt5.order_calc_profit(
        order_type, symbol, float(volume), float(entry), float(stop_loss)
    )
    tp_pnl = mt5.order_calc_profit(
        order_type, symbol, float(volume), float(entry), float(take_profit)
    )
    return (
        float(sl_pnl) if sl_pnl is not None else None,
        float(tp_pnl) if tp_pnl is not None else None,
    )


def _mini_journal_text(selected_date: str | None = None) -> str:
    account = mt5.account_info()
    if account is None:
        return "📒 GOLD_AI — MINI JOURNAL\n\nAccount information unavailable."

    currency = str(account.currency)
    current_balance = float(account.balance)
    current_equity = float(account.equity)

    try:
        period_date = (
            datetime.strptime(selected_date, "%Y-%m-%d").date()
            if selected_date
            else datetime.now().date()
        )
    except ValueError:
        return (
            "📒 GOLD_AI — MINI JOURNAL\n\n"
            "Invalid date. Use /journal YYYY-MM-DD\n"
            "Example: /journal 2026-10-12"
        )

    if period_date > datetime.now().date():
        return "📒 GOLD_AI — MINI JOURNAL\n\nSelected date cannot be in the future."

    now_utc = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        now_utc,
    ) or ()

    grouped: dict[int, list[object]] = {}
    for deal in deals:
        position_id = int(getattr(deal, "position_id", 0) or 0)
        if position_id <= 0:
            continue
        comment = str(getattr(deal, "comment", "") or "")
        magic = int(getattr(deal, "magic", -1))
        if magic != DEMO_MAGIC and not comment.startswith("GOLD_AI:"):
            continue
        grouped.setdefault(position_id, []).append(deal)

    closed_rows: list[dict] = []
    for position_id, position_deals in grouped.items():
        exit_deals = [
            deal for deal in position_deals
            if int(getattr(deal, "entry", -1)) in {
                int(getattr(mt5, "DEAL_ENTRY_OUT", 1)),
                int(getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)),
            }
        ]
        if not exit_deals:
            continue

        pnl = sum(
            float(getattr(deal, "profit", 0.0))
            + float(getattr(deal, "commission", 0.0))
            + float(getattr(deal, "swap", 0.0))
            + float(getattr(deal, "fee", 0.0))
            for deal in position_deals
        )

        strategy = "UNKNOWN"
        for deal in position_deals:
            comment = str(getattr(deal, "comment", "") or "")
            if comment.startswith("GOLD_AI:"):
                strategy = comment.split(":", 1)[1] or "UNKNOWN"
                break

        close_time = max(int(getattr(deal, "time", 0) or 0) for deal in exit_deals)
        close_local_date = datetime.fromtimestamp(close_time).date() if close_time else None
        closed_rows.append({
            "position_id": position_id,
            "pnl": pnl,
            "strategy": strategy,
            "date": close_local_date,
        })

    def stats(rows: list[dict]) -> tuple[int, int, int, float, float]:
        trades = len(rows)
        wins = sum(1 for row in rows if row["pnl"] > 0)
        losses = sum(1 for row in rows if row["pnl"] < 0)
        net = sum(float(row["pnl"]) for row in rows)
        gross_profit = sum(float(row["pnl"]) for row in rows if row["pnl"] > 0)
        gross_loss = abs(sum(float(row["pnl"]) for row in rows if row["pnl"] < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
        return trades, wins, losses, net, pf

    period_rows = [row for row in closed_rows if row["date"] == period_date]
    p_trades, p_wins, p_losses, p_net, p_pf = stats(period_rows)
    a_trades, a_wins, a_losses, a_net, a_pf = stats(closed_rows)

    period_wr = (100.0 * p_wins / p_trades) if p_trades else 0.0
    all_wr = (100.0 * a_wins / a_trades) if a_trades else 0.0
    period_pf_text = "∞" if p_pf == float("inf") else f"{p_pf:.2f}"
    all_pf_text = "∞" if a_pf == float("inf") else f"{a_pf:.2f}"

    # Reconstruct account balance at the start of the selected local date by
    # removing every balance-impacting deal from that date onward from the
    # current balance. This includes manual trades/deposits/withdrawals too,
    # so the denominator is the real account starting balance for that date.
    start_of_period = datetime.combine(period_date, datetime.min.time())
    balance_change_since_start = 0.0
    for deal in deals:
        deal_time = int(getattr(deal, "time", 0) or 0)
        if deal_time <= 0:
            continue
        if datetime.fromtimestamp(deal_time) < start_of_period:
            continue
        balance_change_since_start += (
            float(getattr(deal, "profit", 0.0))
            + float(getattr(deal, "commission", 0.0))
            + float(getattr(deal, "swap", 0.0))
            + float(getattr(deal, "fee", 0.0))
        )

    starting_balance = current_balance - balance_change_since_start
    roi_pct = (100.0 * p_net / starting_balance) if starting_balance > 0 else 0.0

    open_positions = _bot_positions()
    floating = sum(float(getattr(p, "profit", 0.0)) for p in open_positions.values())

    strategy_totals: dict[str, float] = {}
    strategy_counts: dict[str, int] = {}
    for row in period_rows:
        strategy = str(row["strategy"])
        strategy_totals[strategy] = strategy_totals.get(strategy, 0.0) + float(row["pnl"])
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

    label = "TODAY" if period_date == datetime.now().date() else period_date.isoformat()
    lines = [
        "📒 GOLD_AI — MINI JOURNAL",
        "",
        label,
        f"Starting balance: {_fmt_money(starting_balance, currency).lstrip('+')}",
        f"Current balance:  {_fmt_money(current_balance, currency).lstrip('+')}",
        f"Current equity:   {_fmt_money(current_equity, currency).lstrip('+')}",
        f"ROI: {roi_pct:+.2f}%",
        "",
        f"Trades: {p_trades} | W: {p_wins} | L: {p_losses} | WR: {period_wr:.1f}%",
        f"Net P/L: {_fmt_money(p_net, currency)}",
        f"Profit Factor: {period_pf_text}",
        "",
        "ALL TIME",
        f"Trades: {a_trades} | W: {a_wins} | L: {a_losses} | WR: {all_wr:.1f}%",
        f"Net P/L: {_fmt_money(a_net, currency)}",
        f"Profit Factor: {all_pf_text}",
        "",
        f"Open positions: {len(open_positions)}",
        f"Floating P/L: {_fmt_money(floating, currency)}",
    ]

    if strategy_totals:
        lines.extend(["", f"BY STRATEGY — {label}"])
        for strategy in sorted(strategy_totals):
            lines.append(
                f"{strategy}: {_fmt_money(strategy_totals[strategy], currency)} "
                f"({strategy_counts[strategy]} trades)"
            )

    return "\n".join(lines)


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
    orders_log: Path | None = None
    executed: set[str] = set()
    telegram_trade_messages: dict[int, int] = {}

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_admin_raw = os.getenv("TELEGRAM_ADMIN_ID", "").strip()
    tg_admin = int(tg_admin_raw) if tg_admin_raw.isdigit() else 0
    telegram = TelegramController(tg_token, tg_admin)
    ai_shadow = AIShadowEvaluator(REPORTS_DIR)
    ai_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gold-ai-shadow")

    clients: dict[str, MT5Client] = {}

    try:
        clients, _ = _build_market_stack()
        if not clients:
            raise RuntimeError(
                "No deployment markets configured. Set GOLD_AI_MARKETS explicitly "
                "(for example XAUUSD,US30) before demo execution."
            )

        primary_symbol = next(iter(clients.values())).symbol
        guard = DemoExecutor(
            primary_symbol,
            DEMO_RISK_PCT,
            DEMO_MAGIC,
            MAX_TOTAL_OPEN_RISK_PCT,
            SMALL_ACCOUNT_MAX_RISK_PCT,
        )
        account = guard.assert_trading_account()

        # Keep dedup/order history isolated per MT5 account so switching accounts
        # does not make a fresh account inherit signal keys from another login.
        orders_log = Path(REPORTS_DIR) / f"demo_orders_{account['login']}.jsonl"
        executed = _load_executed(orders_log)

        needs_sweep_flip_sessions = False
        if needs_sweep_flip_sessions:
            session_values = {
                "asian_start_hour": ASIAN_START_HOUR,
                "asian_end_hour": ASIAN_END_HOUR,
                "london_start_hour": LONDON_START_HOUR,
                "london_end_hour": LONDON_END_HOUR,
            }
            if any(v is None for v in session_values.values()):
                raise RuntimeError(
                    "US30 M15 Sweep & Flip session boundaries are not configured. "
                    "Set GOLD_AI_ASIAN_START_HOUR, GOLD_AI_ASIAN_END_HOUR, "
                    "GOLD_AI_LONDON_START_HOUR and GOLD_AI_LONDON_END_HOUR "
                    "in the same timezone used by the MT5 candle timestamps."
                )

        registries = {
            market: StrategyRegistry(market=market)
            for market in clients
        }
        executors = {
            market: DemoExecutor(
                client.symbol,
                DEMO_RISK_PCT,
                DEMO_MAGIC,
                MAX_TOTAL_OPEN_RISK_PCT,
                SMALL_ACCOUNT_MAX_RISK_PCT,
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
            journal_text=_mini_journal_text(),
        )
        telegram.set_journal_provider(_mini_journal_text)
        telegram.start()
        last_journal_refresh = time.monotonic()

        print("GOLD_AI MULTI-MARKET TRADER")
        print(f"ACCOUNT       : {account['login']} @ {account['server']}")
        print(f"ACCOUNT TYPE  : {account['account_type']}")
        print("LIVE ACCESS   : ALLOWED (strict risk guard remains active)")
        print(f"MARKETS       : {market_text}")
        print("TIMEFRAME     : M5")
        print(f"RISK / TRADE  : STRICT {DEMO_RISK_PCT}% of current equity")
        print(f"STRATEGIES    : {strategy_text}")
        print("DAILY CAPS    : DISABLED")
        if needs_sweep_flip_sessions:
            print(
                f"SESSIONS      : Asian {ASIAN_START_HOUR:02d}:00-{ASIAN_END_HOUR:02d}:00 | "
                f"London {LONDON_START_HOUR:02d}:00-{LONDON_END_HOUR:02d}:00 "
                "(MT5 candle timezone)"
            )
        else:
            print("SESSIONS      : N/A for current Gold-only routing")
        print(
            "OPEN RISK CAP : "
            + (
                f"{MAX_TOTAL_OPEN_RISK_PCT}% across all GOLD_AI positions"
                if MAX_TOTAL_OPEN_RISK_PCT is not None
                else "DISABLED"
            )
        )
        print(
            f"SMALL ACCOUNT : minimum-lot adaptation allowed up to "
            f"{SMALL_ACCOUNT_MAX_RISK_PCT}% risk/trade"
        )
        print(
            "M15 TRAILING  : "
            + (
                f"ON after {M15_TRAIL_ACTIVATE_R}R; M5 swing span={M15_TRAIL_SWING_SPAN}; "
                f"buffer={M15_TRAIL_ATR_BUFFER} ATR"
                if M15_TRAILING_ENABLED else "OFF"
            )
        )
        print(
            f"AI MODE       : SHADOW / GROQ {ai_shadow.model} / "
            + ("CONFIGURED" if ai_shadow.api_key else "KEY MISSING")
        )
        print("CONCURRENCY   : RISK-BASED (no simple trade-count cap)")
        print("OPPOSITE SIDE : ALLOWED IF THE MT5 ACCOUNT SUPPORTS HEDGING")
        print(f"POLLING       : every {DEMO_POLL_SECONDS}s")
        print(f"TELEGRAM      : {'ENABLED' if telegram.configured else 'DISABLED - env vars missing'}")
        print(f"DEDUP RESTORE : {len(executed)} persisted signal keys")
        print("STATUS        : RUNNING - Ctrl+C to stop")

        if telegram.configured:
            telegram.notify(
                "🤖 GOLD_AI — ONLINE\n\n"
                f"Account: {account['account_type']} • {account['login']}\n"
                f"Broker: {account['server']}\n"
                f"Markets: {market_text}\n"
                f"Risk: STRICT {DEMO_RISK_PCT}% per trade\n"
                "Daily caps: OFF\n"
                f"Max total open risk: "
                + (
                    f"{MAX_TOTAL_OPEN_RISK_PCT}%\n"
                    if MAX_TOTAL_OPEN_RISK_PCT is not None
                    else "DISABLED\n"
                )
                + f"Strategies: {strategy_text}\n"
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
                            if orders_log is None:
                                raise RuntimeError("Account-specific order journal is not initialized.")
                            _log(orders_log, row)

                            # AI review is deliberately submitted AFTER the deterministic
                            # execution decision. It cannot veto, delay, resize or alter
                            # the trade. One background worker keeps API latency out of
                            # the execution loop.
                            recent_context = candles.iloc[-13:-1][
                                ["time", "open", "high", "low", "close"]
                            ].to_dict("records")
                            ai_payload = {
                                "market": market,
                                "symbol": client.symbol,
                                "signal": asdict(signal),
                                "execution_result": asdict(result),
                                "recent_m5": recent_context,
                            }
                            ai_pool.submit(ai_shadow.evaluate_and_log, ai_payload)

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

                            if result.sent:
                                side_icon = "🟢" if signal.direction == "BUY" else "🔴"
                                account_now = mt5.account_info()
                                currency = str(account_now.currency) if account_now else str(account.get("currency", ""))
                                sl_pnl, tp_pnl = _estimate_trade_pnl(
                                    client.symbol,
                                    signal.direction,
                                    result.volume,
                                    result.price,
                                    result.stop_loss,
                                    result.take_profit,
                                )
                                sl_cash = _fmt_money(sl_pnl, currency) if sl_pnl is not None else "estimate unavailable"
                                tp_cash = _fmt_money(tp_pnl, currency) if tp_pnl is not None else "estimate unavailable"

                                message_id = telegram.notify(
                                    "🚀 GOLD_AI — NEW TRADE\n\n"
                                    f"Market: {market}\n"
                                    f"Strategy: {signal.strategy_id}\n"
                                    f"{side_icon} {signal.direction} {client.symbol}\n"
                                    f"Size: {result.volume} lot\n\n"
                                    f"Entry: {_fmt_price(result.price)}\n"
                                    f"SL:    {_fmt_price(result.stop_loss)} ({sl_cash})\n"
                                    f"TP:    {_fmt_price(result.take_profit)} ({tp_cash})\n\n"
                                    f"Planned risk: {result.planned_risk_pct:.3f}% "
                                    f"(~{result.planned_risk_cash:.2f} {currency})\n"
                                    f"Portfolio after entry: {result.portfolio_post_trade_risk_pct:.3f}% "
                                    + (
                                        f"/ {MAX_TOTAL_OPEN_RISK_PCT:.3f}%"
                                        if MAX_TOTAL_OPEN_RISK_PCT is not None
                                        else "/ cap disabled"
                                    )
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
                        telegram.notify(
                            summary,
                            reply_to_message_id=telegram_trade_messages.get(ticket),
                        )
                        telegram_trade_messages.pop(ticket, None)

                account_now = mt5.account_info()
                journal_snapshot = None
                if time.monotonic() - last_journal_refresh >= 30:
                    journal_snapshot = _mini_journal_text()
                    last_journal_refresh = time.monotonic()

                telegram.update_snapshot(
                    status={
                        "account": f"{account_now.login} @ {account_now.server}" if account_now else "-",
                        "symbol": market_text,
                        "balance": f"{account_now.balance:.2f} {account_now.currency}" if account_now else "-",
                        "equity": f"{account_now.equity:.2f} {account_now.currency}" if account_now else "-",
                        "positions": len(current_positions),
                    },
                    positions_text=_positions_text(current_positions),
                    journal_text=journal_snapshot,
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
        ai_pool.shutdown(wait=False, cancel_futures=True)
        MT5Client.shutdown()


if __name__ == "__main__":
    main()
