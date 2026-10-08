from __future__ import annotations

from datetime import datetime, timezone

import MetaTrader5 as mt5

from broker.mt5_client import MT5Client
from config import M15_BARS, M5_BARS, REPORTS_DIR, SYMBOL_HINT
from reporting.reporter import Reporter


def main() -> None:
    reporter = Reporter(REPORTS_DIR)
    client = MT5Client(SYMBOL_HINT)

    try:
        status = client.connect()
        account = client.account_snapshot()

        m5 = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
        m15 = client.candles(mt5.TIMEFRAME_M15, M15_BARS)

        account_path = reporter.save_account_snapshot(account)
        m5_path = reporter.save_candles(m5, "m5")
        m15_path = reporter.save_candles(m15, "m15")
        health_path = reporter.append_health_event(
            {
                "time_utc": datetime.now(timezone.utc).isoformat(),
                "status": "OK",
                "symbol": client.symbol,
                "account_login": status.account_login,
                "server": status.account_server,
                "terminal_path": status.terminal_path,
                "m5_rows": len(m5),
                "m15_rows": len(m15),
            }
        )

        print("GOLD_AI Phase 1 connection test")
        print(f"MT5 connected : {status.connected}")
        print(f"Terminal      : {status.terminal_path}")
        print(f"Account       : {status.account_login} @ {status.account_server}")
        print(f"Symbol        : {client.symbol}")
        print(f"M5 candles    : {len(m5)}")
        print(f"M15 candles   : {len(m15)}")
        print(f"Reports       : {REPORTS_DIR}")
        print(f"Account file  : {account_path.name}")
        print(f"M5 file       : {m5_path.name}")
        print(f"M15 file      : {m15_path.name}")
        print(f"Health file   : {health_path.name}")
        print("LIVE TRADING  : DISABLED")
        print("AI MODE       : SHADOW (provider not connected yet)")

    except Exception as exc:
        reporter.append_health_event(
            {
                "time_utc": datetime.now(timezone.utc).isoformat(),
                "status": "ERROR",
                "error": str(exc),
            }
        )
        raise
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
