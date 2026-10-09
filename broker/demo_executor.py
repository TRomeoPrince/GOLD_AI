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
    planned_risk_cash: float = 0.0
    planned_risk_pct: float = 0.0


class DemoExecutor:
    """MT5 market-order executor with hard demo-account and risk guards."""

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

        # Floor, never round upward. This is important: broker volume
        # normalization must not increase planned account risk.
        volume = floor(raw_volume / step) * step
        volume = min(max(volume, vmin), vmax)
        return round(volume, 8)

    def _loss_for_volume(self, direction: str, volume: float, entry: float, stop_loss: float) -> float:
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        loss = mt5.order_calc_profit(order_type, self.symbol, float(volume), entry, stop_loss)
        if loss is None:
            code, message = mt5.last_error()
            raise RuntimeError(f"order_calc_profit failed: {code} | {message}")
        return abs(float(loss))

    def volume_for_risk(self, direction: str, entry: float, stop_loss: float) -> tuple[float, float, float]:
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("Account info unavailable during risk calculation.")

        equity = float(account.equity)
        risk_cash = equity * (self.risk_pct / 100.0)
        loss_one_lot = self._loss_for_volume(direction, 1.0, entry, stop_loss)
        if loss_one_lot <= 0:
            raise RuntimeError("Calculated stop loss for 1 lot is zero.")

        volume = self._normalize_volume(risk_cash / loss_one_lot)
        if volume <= 0:
            return 0.0, risk_cash, 0.0

        planned_loss = self._loss_for_volume(direction, volume, entry, stop_loss)

        # Strict enforcement: after broker lot-step normalization, planned loss
        # may never exceed the configured risk budget. Tiny floating-point
        # tolerance only; no intentional risk overshoot is permitted.
        tolerance = max(0.01, risk_cash * 0.0001)
        if planned_loss > risk_cash + tolerance:
            return 0.0, risk_cash, planned_loss

        return volume, risk_cash, planned_loss

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
        info = mt5.symbol_info(self.symbol)
        advertised = int(getattr(info, "filling_mode", -1)) if info is not None else -1

        candidates: list[int] = []
        if advertised & 1:
            candidates.append(int(mt5.ORDER_FILLING_FOK))
        if advertised & 2:
            candidates.append(int(mt5.ORDER_FILLING_IOC))
        candidates.append(int(mt5.ORDER_FILLING_RETURN))

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

        volume, risk_budget, planned_loss = self.volume_for_risk(
            signal.direction, price, signal.stop_loss
        )
        account = mt5.account_info()
        equity = float(account.equity) if account else 0.0
        planned_pct = (100.0 * planned_loss / equity) if equity > 0 else 0.0

        if volume <= 0:
            reason = (
                "SKIPPED_RISK: calculated volume is below broker minimum."
                if planned_loss <= 0
                else
                f"SKIPPED_RISK_GUARD: broker-normalized order would risk "
                f"{planned_loss:.2f}, above the {risk_budget:.2f} budget."
            )
            return DemoOrderResult(
                False, signal.strategy_id, signal.direction, 0.0, price,
                signal.stop_loss, signal.take_profit, None, None, reason,
                planned_loss, planned_pct,
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
                planned_loss, planned_pct,
            )

        request["type_filling"] = fill_mode
        result = mt5.order_send(request)
        if result is None:
            code, message = mt5.last_error()
            return DemoOrderResult(
                False, signal.strategy_id, signal.direction, volume, price,
                signal.stop_loss, signal.take_profit, None, None,
                f"ORDER_SEND_FAILED [{fill_detail}]: {code} | {message}",
                planned_loss, planned_pct,
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
            planned_loss, planned_pct,
        )
