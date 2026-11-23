from __future__ import annotations

from dataclasses import dataclass, field
from math import floor, isfinite
from datetime import datetime, timedelta, timezone
import time

import MetaTrader5 as mt5
from broker.clock import tick_epoch, tick_utc_epoch
from broker.symbols import resolve_symbol
from strategies.execution_prices import target_at_executable_price

MAGIC = 560090


@dataclass
class ExecutionResult:
    sent: bool
    ticket: int | None
    message: str
    volume: float = 0.0
    planned_risk_pct: float = 0.0
    portfolio_after_pct: float = 0.0
    details: dict = field(default_factory=dict)


def _resolve_symbol(hint: str) -> str:
    return resolve_symbol(mt5, hint)


def _loss(direction: str, symbol: str, volume: float, entry: float, sl: float) -> float:
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    pnl = mt5.order_calc_profit(order_type, symbol, volume, entry, sl)
    if pnl is None:
        raise RuntimeError(f"Risk calculation failed: {mt5.last_error()}")
    if not isfinite(float(pnl)):
        raise RuntimeError("Risk calculation returned a non-finite value; order blocked.")
    return abs(min(float(pnl), 0.0))


def _volume_for_risk(
    direction: str,
    symbol: str,
    entry: float,
    sl: float,
    target_risk_pct: float,
    max_single_risk_pct: float,
) -> tuple[float, float]:
    account = mt5.account_info()
    info = mt5.symbol_info(symbol)
    if account is None or info is None:
        raise RuntimeError("Account/symbol info unavailable.")

    equity = float(account.equity)
    if not isfinite(equity) or equity <= 0:
        raise RuntimeError("Account equity is invalid; order blocked.")
    target_cash = equity * target_risk_pct / 100.0
    loss_one = _loss(direction, symbol, 1.0, entry, sl)
    if loss_one <= 0:
        raise RuntimeError("Invalid stop-loss risk.")

    raw = target_cash / loss_one
    vmin, vmax, step = float(info.volume_min), float(info.volume_max), float(info.volume_step)
    if not all(isfinite(value) and value > 0 for value in (vmin, vmax, step)) or vmax < vmin:
        raise RuntimeError("Invalid broker volume limits; order blocked.")
    if raw < vmin:
        planned = _loss(direction, symbol, vmin, entry, sl)
        pct = 100.0 * planned / equity
        return (vmin, pct) if pct <= max_single_risk_pct else (0.0, pct)

    volume = floor(raw / step) * step
    volume = min(max(volume, vmin), vmax)
    volume = round(volume, 8)
    planned = _loss(direction, symbol, volume, entry, sl)
    pct = 100.0 * planned / equity
    if pct > max_single_risk_pct:
        return 0.0, pct
    return volume, pct


def _open_risk_pct(include_all_positions=False) -> float:
    account = mt5.account_info()
    if account is None or not isfinite(float(account.equity)) or float(account.equity) <= 0:
        return float("inf")
    equity = float(account.equity)
    positions = mt5.positions_get()
    if positions is None:
        return float("inf")  # Query failure is not an empty portfolio.
    total = 0.0
    for p in positions:
        if not include_all_positions and int(getattr(p, "magic", -1)) != MAGIC:
            continue
        sl = float(getattr(p, "sl", 0.0) or 0.0)
        if sl <= 0:
            return float("inf")
        direction = "BUY" if int(p.type) == int(mt5.POSITION_TYPE_BUY) else "SELL"
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        pnl = mt5.order_calc_profit(
            order_type,
            str(p.symbol),
            float(p.volume),
            float(p.price_open),
            sl,
        )
        if pnl is None:
            return float("inf")
        if not isfinite(float(pnl)):
            return float("inf")
        total += abs(min(float(pnl), 0.0))
    return 100.0 * total / equity


def _daily_change_pct(account, *, strict, offset_seconds) -> float:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Daily limits use a UTC day. Translate its query boundaries into the
    # calibrated broker clock, as the history reconciliation worker does.
    offset = timedelta(seconds=offset_seconds)
    deals = mt5.history_deals_get(start + offset, now + offset)
    if strict and deals is None:
        raise RuntimeError("Daily MT5 history unavailable; order blocked.")
    deals = deals or ()

    realized = 0.0
    for deal in deals:
        amounts = [float(getattr(deal, field, 0) or 0) for field in ("profit", "commission", "swap", "fee")]
        if not all(isfinite(amount) for amount in amounts):
            raise RuntimeError("Daily MT5 history contains invalid values; order blocked.")
        realized += sum(amounts)

    start_balance = float(account.balance) - realized
    if not isfinite(start_balance) or start_balance <= 0:
        raise RuntimeError("Daily MT5 starting balance is invalid; order blocked.")
    return 100.0 * (float(account.equity) - start_balance) / start_balance


def execute_instruction(
    payload: dict,
    risk_per_trade_pct: float,
    max_open_risk_pct: float,
    max_daily_loss_pct: float,
    daily_profit_target_enabled: bool = False,
    daily_profit_target_pct: float = 0.0,
    *,
    max_single_risk_pct: float = 15.0,
    before_send=None,
    include_all_positions: bool = False,
    strict_history: bool = False,
) -> ExecutionResult:
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None:
        raise RuntimeError("MT5 terminal/account unavailable.")
    if not all(isfinite(float(getattr(account, field))) for field in ("equity", "balance")) or float(account.equity) <= 0:
        return ExecutionResult(False, None, "Account equity/balance invalid; order blocked.")
    controls = (risk_per_trade_pct, max_open_risk_pct, max_daily_loss_pct, max_single_risk_pct)
    if daily_profit_target_enabled:
        controls += (daily_profit_target_pct,)
    if not all(isfinite(float(value)) and float(value) > 0 for value in controls):
        return ExecutionResult(False, None, "Invalid risk policy; order blocked.")
    max_single_risk_pct = min(15.0, float(max_single_risk_pct))
    max_open_risk_pct = min(40.0, float(max_open_risk_pct))
    max_daily_loss_pct = min(10.0, float(max_daily_loss_pct))
    if not bool(getattr(terminal, "trade_allowed", False)):
        return ExecutionResult(False, None, "Algo Trading is disabled.")

    direction = str(payload["direction"]).upper()
    if direction not in {"BUY", "SELL"}:
        raise ValueError("Unsupported trade direction.")
    symbol = _resolve_symbol(
        str(payload.get("market") or payload.get("symbol_hint") or "GOLD")
    )
    sl = float(payload["stop_loss"])
    tp = float(payload["take_profit"])
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return ExecutionResult(False, None, f"No live tick for {symbol}.")

    offset_seconds = 0
    if strict_history:
        try:
            quote_utc = tick_utc_epoch(mt5, symbol, tick)
            quote_age = time.time() - quote_utc
            offset_seconds = round(tick_epoch(tick) - quote_utc)
        except RuntimeError as exc:
            return ExecutionResult(False, None, f"STALE_QUOTE: {exc}")
        if not -5 <= quote_age <= 120:
            return ExecutionResult(False, None, "STALE_QUOTE: no recent broker tick.")

    daily_change = _daily_change_pct(account, strict=strict_history, offset_seconds=offset_seconds)
    if daily_profit_target_enabled and daily_change >= float(daily_profit_target_pct):
        return ExecutionResult(
            False, None,
            f"DAILY_PROFIT_TARGET_REACHED: {daily_change:.2f}% >= {float(daily_profit_target_pct):.2f}%.",
        )
    daily_loss = max(0.0, -daily_change)
    if daily_loss >= max_daily_loss_pct:
        return ExecutionResult(
            False, None,
            f"DAILY_LOSS_BLOCKED: {daily_loss:.2f}% >= {max_daily_loss_pct:.2f}%.",
        )

    price = float(tick.ask if direction == "BUY" else tick.bid)
    valid = sl < price < tp if direction == "BUY" else tp < price < sl
    if not valid:
        return ExecutionResult(
            False,
            None,
            "STALE_SIGNAL: current price is outside SL/TP geometry.",
        )
    if str(payload.get("strategy_id")) == "M15_BREAKOUT":
        # The signal's retest-close price is a reference, NOT a guaranteed fill.
        # Keep the structural SL unchanged, size risk from the live quote, and
        # restore the intended R multiple before broker order_check/order_send.
        metadata = payload.get("metadata") or {}
        features = metadata.get("features") if isinstance(metadata, dict) else {}
        if not isinstance(features, dict) or "reward_r" not in features:
            return ExecutionResult(False, None, "INVALID_M15_SIGNAL: missing reward_r.")
        try:
            tp = target_at_executable_price(direction, price, sl, features["reward_r"])
        except (ValueError, TypeError) as exc:
            return ExecutionResult(False, None, f"INVALID_M15_SIGNAL: {exc}")

    volume, single_pct = _volume_for_risk(
        direction,
        symbol,
        price,
        sl,
        float(risk_per_trade_pct),
        min(float(risk_per_trade_pct), max_open_risk_pct, max_single_risk_pct),
    )
    if volume <= 0:
        return ExecutionResult(
            False,
            None,
            f"RISK_BLOCKED: broker minimum would risk {single_pct:.2f}%.",
            planned_risk_pct=single_pct,
        )

    open_pct = _open_risk_pct(include_all_positions)
    post_pct = open_pct + single_pct
    if post_pct > float(max_open_risk_pct) + 0.001:
        return ExecutionResult(
            False,
            None,
            f"PORTFOLIO_RISK_BLOCKED: {post_pct:.2f}% > {float(max_open_risk_pct):.2f}%.",
            volume=volume,
            planned_risk_pct=single_pct,
            portfolio_after_pct=post_pct,
        )

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    base = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": MAGIC,
        "comment": f"AZT:{str(payload.get('strategy_id','REMOTE'))}"[:31],
        "type_time": mt5.ORDER_TIME_GTC,
    }

    info = mt5.symbol_info(symbol)
    advertised = int(getattr(info, "filling_mode", -1)) if info is not None else -1
    candidates = []
    if advertised & 1:
        candidates.append(int(mt5.ORDER_FILLING_FOK))
    if advertised & 2:
        candidates.append(int(mt5.ORDER_FILLING_IOC))
    candidates += [
        int(mt5.ORDER_FILLING_RETURN),
        int(mt5.ORDER_FILLING_FOK),
        int(mt5.ORDER_FILLING_IOC),
    ]

    tried = set()
    for mode in candidates:
        if mode in tried:
            continue
        tried.add(mode)
        request = dict(base)
        request["type_filling"] = mode
        check = mt5.order_check(request)
        if check is None or int(check.retcode) != 0:
            continue
        if before_send is not None:
            before_send()
        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError("MT5 submission returned no result; review broker orders before retrying.")
        done = int(result.retcode) in {
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
            int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)),
        }
        ticket = int(
            getattr(result, "order", 0) or getattr(result, "deal", 0) or 0
        ) or None
        details = {}
        if done:
            try:
                from .trade_events import execution_details
                details = execution_details(mt5, result, request, payload, ticket=ticket, risk_pct=single_pct,
                                            portfolio_after_pct=post_pct, max_open_risk_pct=max_open_risk_pct, verified_account=account)
            except Exception:
                # A confirmed broker result must survive optional presentation failure.
                pass
        return ExecutionResult(
            done,
            ticket,
            str(getattr(result, "comment", "")),
            volume,
            single_pct,
            post_pct,
            details,
        )

    return ExecutionResult(
        False,
        None,
        "ORDER_REJECTED: no supported filling mode.",
        volume,
        single_pct,
        post_pct,
    )
