"""Headway-specific REAL-account executor. Not used by demo_bot.py."""
from __future__ import annotations

import os

import MetaTrader5 as mt5

from broker.demo_executor import DemoExecutor, DemoOrderResult


class HeadwayLiveExecutor(DemoExecutor):
    """One minimum-lot trade, unchanged strategy SL/TP, conservative cash-risk cap."""

    HARD_MAX_RISK_USD = 5.0
    MAX_EQUITY_FRACTION = 0.50
    RISK_BUFFER = 1.10  # estimated loss can be exceeded by slippage/gaps/fees

    def __init__(self, symbol: str, magic: int, authorized_login: int):
        super().__init__(symbol=symbol, risk_pct=0, magic=magic)
        self.authorized_login = int(authorized_login)

    def assert_demo_account(self) -> dict:
        """Override parent demo guard with a strict live Headway account guard."""
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        if account is None or terminal is None:
            raise RuntimeError("MT5 account/terminal unavailable.")
        if os.getenv("HEADWAY_LIVE_ENABLED", "").strip() != "YES":
            raise RuntimeError("LIVE BLOCKED: HEADWAY_LIVE_ENABLED must equal YES.")
        if int(account.login) != self.authorized_login:
            raise RuntimeError("LIVE BLOCKED: connected MT5 account differs from HEADWAY_LIVE_ACCOUNT.")
        if int(account.trade_mode) != int(mt5.ACCOUNT_TRADE_MODE_REAL):
            raise RuntimeError("LIVE BLOCKED: account is not MT5 REAL.")
        if "headway" not in str(account.server).lower():
            raise RuntimeError("LIVE BLOCKED: MT5 server is not Headway.")
        if str(account.currency).upper() != "USD":
            raise RuntimeError("LIVE BLOCKED: account currency is not USD.")
        if not bool(getattr(terminal, "trade_allowed", False)):
            raise RuntimeError("LIVE BLOCKED: enable Algo Trading in MT5.")
        return {
            "login": int(account.login),
            "server": str(account.server),
            "balance": float(account.balance),
            "equity": float(account.equity),
            "currency": str(account.currency),
        }

    def volume_for_risk(self, direction: str, entry: float, stop_loss: float) -> float:
        account = mt5.account_info()
        info = mt5.symbol_info(self.symbol)
        if account is None or info is None:
            raise RuntimeError("Account or symbol specifications unavailable.")
        minimum = float(info.volume_min)
        if minimum <= 0 or float(info.volume_step) <= 0:
            raise RuntimeError("Invalid broker minimum volume/step.")
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        pnl_at_stop = mt5.order_calc_profit(order_type, self.symbol, minimum, entry, stop_loss)
        if pnl_at_stop is None:
            raise RuntimeError(f"MT5 stop-loss estimate failed: {mt5.last_error()}")
        loss = -float(pnl_at_stop)
        if loss <= 0:
            raise RuntimeError("Invalid non-loss stop calculation; refusing order.")
        equity = float(account.equity)
        if equity <= 0:
            return 0.0
        risk_ceiling = min(self.HARD_MAX_RISK_USD, equity * self.MAX_EQUITY_FRACTION)
        if loss * self.RISK_BUFFER > risk_ceiling:
            print(
                f"[HEADWAY RISK SKIP] Minimum {minimum} lot planned loss "
                f"{loss:.2f} USD (buffered {loss * self.RISK_BUFFER:.2f}) "
                f"> ceiling {risk_ceiling:.2f} USD"
            )
            return 0.0
        return minimum  # never enlarge volume to spend the risk allowance

    def send(self, signal) -> DemoOrderResult:
        self.assert_demo_account()
        if mt5.positions_get() is None:
            raise RuntimeError(f"Cannot verify existing positions: {mt5.last_error()}")
        if mt5.positions_get():
            return self._skip(signal, "SKIPPED_POSITION: one-position limit applies account-wide.")
        pending = mt5.orders_get()
        if pending is None:
            raise RuntimeError(f"Cannot verify pending orders: {mt5.last_error()}")
        if pending:
            return self._skip(signal, "SKIPPED_PENDING: account has pending orders.")
        info = mt5.symbol_info(self.symbol)
        tick = mt5.symbol_info_tick(self.symbol)
        if info is None or tick is None:
            raise RuntimeError("Cannot read symbol or tick.")
        spread = float(tick.ask) - float(tick.bid)
        max_spread = 0.60
        if spread < 0 or spread > max_spread:
            return self._skip(signal, f"SKIPPED_SPREAD: {spread:.2f} > {max_spread:.2f} gold points.")
        price = float(tick.ask if signal.direction == "BUY" else tick.bid)
        min_volume = float(info.volume_min)
        order_type = mt5.ORDER_TYPE_BUY if signal.direction == "BUY" else mt5.ORDER_TYPE_SELL
        margin = mt5.order_calc_margin(order_type, self.symbol, min_volume, price)
        account = mt5.account_info()
        if margin is None or account is None or float(margin) > float(account.margin_free) * 0.80:
            return self._skip(signal, "SKIPPED_MARGIN: minimum lot needs too much free margin.")
        # Parent retains original SL/TP and broker order_check; its calls to
        # assert_demo_account/volume_for_risk dispatch to these guarded overrides.
        return super().send(signal)

    @staticmethod
    def _skip(signal, message: str) -> DemoOrderResult:
        return DemoOrderResult(
            False, signal.strategy_id, signal.direction, 0.0,
            float(signal.entry), float(signal.stop_loss), float(signal.take_profit),
            None, None, message,
        )
