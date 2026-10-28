from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd
from .clock import BrokerClock
from .symbols import resolve_symbol


@dataclass(frozen=True)
class ConnectionStatus:
    connected: bool
    terminal_path: str
    account_login: Optional[int]
    account_server: str


class MT5Client:
    def __init__(self, symbol_hint: str = "XAUUSD") -> None:
        self.symbol_hint = symbol_hint
        self.symbol: Optional[str] = None
        self.clock: Optional[BrokerClock] = None

    def connect(self) -> ConnectionStatus:
        if not mt5.initialize():
            code, message = mt5.last_error()
            raise RuntimeError(f"MT5 initialize failed: {code} | {message}")

        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if terminal is None or account is None or not getattr(terminal, "connected", False):
            code, message = mt5.last_error()
            mt5.shutdown()
            raise RuntimeError(f"MT5 terminal/account unavailable or disconnected: {code} | {message}")

        self.symbol = self._resolve_symbol()
        self.clock = BrokerClock.detect(mt5, self.symbol)

        return ConnectionStatus(
            connected=True,
            terminal_path=str(getattr(terminal, "path", "")),
            account_login=int(account.login),
            account_server=str(account.server),
        )

    def _resolve_symbol(self) -> str:
        return resolve_symbol(mt5, self.symbol_hint)

    def account_snapshot(self) -> dict:
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("Could not read MT5 account information.")
        return {
            "login": int(account.login),
            "server": str(account.server),
            "balance": float(account.balance),
            "equity": float(account.equity),
            "margin": float(account.margin),
            "margin_free": float(account.margin_free),
            "currency": str(account.currency),
            "leverage": int(account.leverage),
        }

    def candles(self, timeframe: int, count: int) -> pd.DataFrame:
        if not self.symbol:
            raise RuntimeError("MT5 client is not connected.")

        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            code, message = mt5.last_error()
            raise RuntimeError(
                f"No candle data returned for {self.symbol}: {code} | {message}"
            )

        if self.clock is None:
            raise RuntimeError("MT5 clock was not calibrated at connection.")
        self.clock.validate_tick(mt5.symbol_info_tick(self.symbol))
        frame = pd.DataFrame(rates)
        frame["broker_time"] = frame["time"]
        frame["time"] = pd.to_datetime(self.clock.to_utc_epoch(frame["time"]), unit="s", utc=True)
        frame.attrs["broker_clock_offset_seconds"] = self.clock.offset_seconds
        return frame

    @staticmethod
    def shutdown() -> None:
        mt5.shutdown()
