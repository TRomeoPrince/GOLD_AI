from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Optional

import MetaTrader5 as mt5

from strategies.base import StrategySignal


@dataclass(frozen=True)
class DemoOrderResult:
    sent: bool
    strategy_id: str
    direction: str
    volume: float
    price: float
    stop_loss: float
    take_profit: float
    ticket: Optional[int]
    retcode: Optional[int]
    message: str


class DemoExecutor:
    """MT5 market-order executor with a hard demo-account guard."""

    def __init__(self, symbol: str, risk_pct: float, magic: int) -> None:
        self.symbol = symbol
        self.risk_pct = float(risk_pct)
        self.magic = int(magic)

    @staticmethod
    def assert_demo_account() -> dict:
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("MT5 account information unavailable.")

        demo_mode = int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))
        trade_mode = int(getattr(account, "trade_mode", -1))
        if trade_mode != demo_mode:
            raise RuntimeError(
                "DEMO EXECUTION BLOCKED: the connected MT5 account is not a demo account. "
                f"login={account.login}, server={account.server}, trade_mode={trade_mode}"
            )

        terminal = mt5.terminal_info()
        if terminal is None:
            raise RuntimeError("MT5 terminal information unavailable.")
        if not bool(getattr(terminal, "trade_allowed", False)):
            raise RuntimeError("MT5 trading is not allowed. Enable Algo Trading in the terminal.")

        return {
            "login": int(account.login),
            "server": str(account.server),
            "balance": float(account.balance),
            "equity": float(account.equity),
            "currency": str(account.currency),
            "trade_mode": trade_mode,
            "margin_mode": int(getattr(account, "margin_mode", -1)),
        }

    def _current_price(self, direction: str) -> float:
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise RuntimeError(f"No live tick for {self.symbol}.")
        price = float(tick.ask if direction == "BUY" else tick.bid)
        if price <= 0:
            raise RuntimeError(f"Invalid market price for {self.symbol}: {price}")
        return price

    def _normalize_volume(self, raw_volume: float) -> float:
        info = mt5.symbol_info(self.symbol)
        if info is None:
            raise RuntimeError(f"Symbol info unavailable for {self.symbol}.")
        vmin = float(info.volume_min)
        vmax = float(info.volume_max)
        step = float(info.volume_step)
        if step <= 0:
            raise RuntimeError(f"Invalid volume step for {self.symbol}.")
        if raw_volume < vmin:
            return 0.0
        volume = floor(raw_volume / step) * step
        volume = min(max(volume, vmin), vmax)
        return round(volume, 8)

    def volume_for_risk(self, direction: str, entry: float, stop_loss: float) -> float:
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("Account info unavailable during risk calculation.")
        risk_cash = float(account.equity) * (self.risk_pct / 100.0)
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        loss_one_lot = mt5.order_calc_profit(order_type, self.symbol, 1.0, entry, stop_loss)
        if loss_one_lot is None:
            code, message = mt5.last_error()
            raise RuntimeError(f"order_calc_profit failed: {code} | {message}")
        loss_one_lot = abs(float(loss_one_lot))
        if loss_one_lot <= 0:
            raise RuntimeError("Calculated stop loss for 1 lot is zero.")
        return self._normalize_volume(risk_cash / loss_one_lot)

    @staticmethod
    def _valid_geometry(signal: StrategySignal, price: float) -> bool:
        if signal.direction == "BUY":
            return signal.stop_loss < price < signal.take_profit
        return signal.take_profit < price < signal.stop_loss

    @staticmethod
    def _fill_name(mode: int) -> str:
        names = {
            int(mt5.ORDER_FILLING_FOK): "FOK",
            int(mt5.ORDER_FILLING_IOC): "IOC",
            int(mt5.ORDER_FILLING_RETURN): "RETURN",
        }
        return names.get(int(mode), str(mode))

    def _select_filling_mode(self, request: dict) -> tuple[Optional[int], Optional[object], str]:
        """Ask MT5 which market-order filling mode this broker/symbol accepts.

        We do not hard-code IOC because brokers can expose different execution
        policies for the same instrument. ORDER_FILLING_BOC is intentionally
        excluded because it is for passive pending/limit-style execution, not
        these market orders.
        """
        info = mt5.symbol_info(self.symbol)
        advertised = int(getattr(info, "filling_mode", -1)) if info is not None else -1

        # Prefer modes the symbol advertises, then let order_check be the final
        # authority. RETURN is tried last because it is not valid for every
        # market-execution symbol.
        candidates: list[int] = []
        if advertised & 1:
            candidates.append(int(mt5.ORDER_FILLING_FOK))
        if advertised & 2:
            candidates.append(int(mt5.ORDER_FILLING_IOC))
        candidates.append(int(mt5.ORDER_FILLING_RETURN))

        # Defensive fallback if the broker's advertised flags are unusual.
        for mode in (int(mt5.ORDER_FILLING_FOK), int(mt5.ORDER_FILLING_IOC)):
            if mode not in candidates:
                candidates.append(mode)

        attempts: list[str] = []
        for mode in candidates:
            candidate = dict(request)
            candidate["type_filling"] = mode
            check = mt5.order_check(candidate)
            if check is None:
                code, message = mt5.last_error()
                attempts.append(f"{self._fill_name(mode)}=CHECK_FAILED({code}:{message})")
                continue

            retcode = int(check.retcode)
            comment = str(getattr(check, "comment", ""))
            if retcode == 0:
                return mode, check, f"{self._fill_name(mode)} (symbol filling_mode={advertised})"

            attempts.append(f"{self._fill_name(mode)}={retcode}:{comment}")

        return None, None, "; ".join(attempts)

    def send(self, signal: StrategySignal) -> DemoOrderResult:
        self.assert_demo_account()
        price = self._current_price(signal.direction)

        if not self._valid_geometry(signal, price):
            return DemoOrderResult(
                False, signal.strategy_id, signal.direction, 0.0, price,
                signal.stop_loss, signal.take_profit, None, None,
                "SKIPPED_STALE: current price is no longer between the strategy SL and TP.",
            )

        volume = self.volume_for_risk(signal.direction, price, signal.stop_loss)
        if volume <= 0:
            return DemoOrderResult(
                False, signal.strategy_id, signal.direction, 0.0, price,
                signal.stop_loss, signal.take_profit, None, None,
                "SKIPPED_RISK: calculated volume is below broker minimum.",
            )

        order_type = mt5.ORDER_TYPE_BUY if signal.direction == "BUY" else mt5.ORDER_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": float(signal.stop_loss),
            "tp": float(signal.take_profit),
            "deviation": 20,
            "magic": self.magic,
            "comment": f"GOLD_AI:{signal.strategy_id}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
        }

        fill_mode, check, fill_detail = self._select_filling_mode(request)
        if fill_mode is None or check is None:
            return DemoOrderResult(
                False, signal.strategy_id, signal.direction, volume, price,
                signal.stop_loss, signal.take_profit, None, None,
                f"ORDER_CHECK_REJECTED: no supported market filling mode. Attempts: {fill_detail}",
            )

        request["type_filling"] = fill_mode
        result = mt5.order_send(request)
        if result is None:
            code, message = mt5.last_error()
            return DemoOrderResult(
                False, signal.strategy_id, signal.direction, volume, price,
                signal.stop_loss, signal.take_profit, None, None,
                f"ORDER_SEND_FAILED [{fill_detail}]: {code} | {message}",
            )

        done_codes = {
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
            int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)),
        }
        sent = int(result.retcode) in done_codes
        ticket = int(getattr(result, "order", 0) or getattr(result, "deal", 0) or 0) or None
        return DemoOrderResult(
            sent, signal.strategy_id, signal.direction, volume, price,
            signal.stop_loss, signal.take_profit, ticket, int(result.retcode),
            f"{getattr(result, 'comment', '')} | filling={fill_detail}",
        )
