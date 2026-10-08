from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd


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

    def connect(self) -> ConnectionStatus:
        if not mt5.initialize():
            code, message = mt5.last_error()
            raise RuntimeError(f"MT5 initialize failed: {code} | {message}")

        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if terminal is None or account is None:
            code, message = mt5.last_error()
            mt5.shutdown()
            raise RuntimeError(f"MT5 terminal/account info unavailable: {code} | {message}")

        self.symbol = self._resolve_symbol()

        return ConnectionStatus(
            connected=True,
            terminal_path=str(getattr(terminal, "path", "")),
            account_login=int(account.login),
            account_server=str(account.server),
        )

    def _resolve_symbol(self) -> str:
        symbols = mt5.symbols_get()
        if not symbols:
            raise RuntimeError("MT5 returned no symbols.")

        hint = self.symbol_hint.upper()
        candidates = [s.name for s in symbols if hint in s.name.upper()]
        if not candidates:
            raise RuntimeError(f"No symbol containing {self.symbol_hint!r} was found.")

        exact = [name for name in candidates if name.upper() == hint]
        chosen = exact[0] if exact else sorted(candidates, key=len)[0]

        info = mt5.symbol_info(chosen)
        if info is None:
            raise RuntimeError(f"Could not read symbol info for {chosen}.")
        if not info.visible and not mt5.symbol_select(chosen, True):
            raise RuntimeError(f"Could not select symbol {chosen} in Market Watch.")

        return chosen

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

        frame = pd.DataFrame(rates)
        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        return frame

    @staticmethod
    def shutdown() -> None:
        mt5.shutdown()
