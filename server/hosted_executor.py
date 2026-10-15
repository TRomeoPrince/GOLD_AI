from __future__ import annotations

from dataclasses import dataclass
from math import floor

import MetaTrader5 as mt5

MAGIC = 560090


@dataclass
class ExecutionResult:
    sent: bool
    ticket: int | None
    message: str
    volume: float = 0.0
    planned_risk_pct: float = 0.0
    portfolio_after_pct: float = 0.0


def _resolve_symbol(hint: str) -> str:
    symbols = mt5.symbols_get() or ()
    upper = hint.upper()
    candidates = [s.name for s in symbols if upper in s.name.upper()]
    if not candidates and upper in {"GOLD", "XAUUSD"}:
        candidates = [
            s.name for s in symbols
            if "XAU" in s.name.upper() or "GOLD" in s.name.upper()
        ]
    if not candidates:
        raise RuntimeError(f"No broker symbol found for {hint}.")
    exact = [x for x in candidates if x.upper() == upper]
    symbol = exact[0] if exact else sorted(candidates, key=len)[0]
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol info unavailable for {symbol}.")
    if not info.visible and not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Could not select {symbol}.")
    return symbol


def _loss(direction: str, symbol: str, volume: float, entry: float, sl: float) -> float:
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    pnl = mt5.order_calc_profit(order_type, symbol, volume, entry, sl)
    if pnl is None:
        raise RuntimeError(f"Risk calculation failed: {mt5.last_error()}")
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
    target_cash = equity * target_risk_pct / 100.0
    loss_one = _loss(direction, symbol, 1.0, entry, sl)
    if loss_one <= 0:
        raise RuntimeError("Invalid stop-loss risk.")

    raw = target_cash / loss_one
    vmin, vmax, step = float(info.volume_min), float(info.volume_max), float(info.volume_step)
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


def _open_risk_pct() -> float:
    account = mt5.account_info()
    if account is None or float(account.equity) <= 0:
        return float("inf")
    equity = float(account.equity)
    total = 0.0
    for p in mt5.positions_get() or ():
        if int(getattr(p, "magic", -1)) != MAGIC:
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
        total += abs(min(float(pnl), 0.0))
    return 100.0 * total / equity


def execute_instruction(
    payload: dict,
    risk_per_trade_pct: float,
    max_open_risk_pct: float,
) -> ExecutionResult:
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None:
        raise RuntimeError("MT5 terminal/account unavailable.")
    if not bool(getattr(terminal, "trade_allowed", False)):
        return ExecutionResult(False, None, "Algo Trading is disabled.")

    direction = str(payload["direction"]).upper()
    symbol = _resolve_symbol(
        str(payload.get("symbol_hint") or payload.get("market") or "XAUUSD")
    )
    sl = float(payload["stop_loss"])
    tp = float(payload["take_profit"])
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return ExecutionResult(False, None, f"No live tick for {symbol}.")

    price = float(tick.ask if direction == "BUY" else tick.bid)
    valid = sl < price < tp if direction == "BUY" else tp < price < sl
    if not valid:
        return ExecutionResult(
            False,
            None,
            "STALE_SIGNAL: current price is outside SL/TP geometry.",
        )

    volume, single_pct = _volume_for_risk(
        direction,
        symbol,
        price,
        sl,
        float(risk_per_trade_pct),
        min(float(max_open_risk_pct), 15.0),
    )
    if volume <= 0:
        return ExecutionResult(
            False,
            None,
            f"RISK_BLOCKED: broker minimum would risk {single_pct:.2f}%.",
            planned_risk_pct=single_pct,
        )

    open_pct = _open_risk_pct()
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
        "comment": f"GOLD_AI:{str(payload.get('strategy_id','REMOTE'))}"[:31],
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
        result = mt5.order_send(request)
        if result is None:
            continue
        done = int(result.retcode) in {
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
            int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)),
        }
        ticket = int(
            getattr(result, "order", 0) or getattr(result, "deal", 0) or 0
        ) or None
        return ExecutionResult(
            done,
            ticket,
            str(getattr(result, "comment", "")),
            volume,
            single_pct,
            post_pct,
        )

    return ExecutionResult(
        False,
        None,
        "ORDER_REJECTED: no supported filling mode.",
        volume,
        single_pct,
        post_pct,
    )
