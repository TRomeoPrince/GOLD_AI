from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import os

import MetaTrader5 as mt5
from dotenv import load_dotenv

from ai.shadow import AIShadowEvaluator
from broker.mt5_client import MT5Client
from config import M15_BARS, M5_BARS, REPORTS_DIR, SYMBOL_HINT
from reporting.reporter import Reporter
from reporting.signal_reporter import SignalReporter
from strategies import StrategyRegistry


def main() -> None:
    load_dotenv()
    reporter = Reporter(REPORTS_DIR)
    signal_reporter = SignalReporter(REPORTS_DIR)
    client = MT5Client(SYMBOL_HINT)
    registry = StrategyRegistry()
    evaluator = AIShadowEvaluator(REPORTS_DIR)

    try:
        status = client.connect()
        account = client.account_snapshot()
        m5 = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
        m15 = client.candles(mt5.TIMEFRAME_M15, M15_BARS)
        account_path = reporter.save_account_snapshot(account)
        m5_path = reporter.save_candles(m5, "m5")
        m15_path = reporter.save_candles(m15, "m15")

        # Frozen deterministic signals: AI cannot veto, add or alter a trade.
        signals = registry.scan(m5)
        signal_reporter.append(signals)
        ai_results = []
        # Evaluate only the latest setup per strategy/direction, if any.
        # No repeated model calls for old historical signals in this scan.
        recent = m5.iloc[-21:-1]
        context = recent[["time", "open", "high", "low", "close"]].tail(12).to_dict("records")
        for signal in signals:
            payload = {"symbol": client.symbol, "signal": asdict(signal), "recent_m5": context}
            ai_results.append(evaluator.evaluate_and_log(payload))

        health_path = reporter.append_health_event({
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "status": "OK",
            "symbol": client.symbol,
            "account_login": status.account_login,
            "server": status.account_server,
            "terminal_path": status.terminal_path,
            "m5_rows": len(m5),
            "m15_rows": len(m15),
            "strategy_models": "|".join(registry.strategy_ids),
            "signals": len(signals),
            "ai_evaluations": len(ai_results),
        })

        print("GOLD_AI - frozen six + independent AI shadow research")
        print(f"MT5 connected : {status.connected}")
        print(f"Account       : {status.account_login} @ {status.account_server}")
        print(f"Symbol        : {client.symbol}")
        print(f"M5 candles    : {len(m5)}")
        print(f"Strategies    : {', '.join(registry.strategy_ids)}")
        print(f"Signals       : {len(signals)}")
        print(f"AI reviews    : {len(ai_results)}")
        print(f"AI provider   : {'Gemini configured' if evaluator.api_key else 'No key configured'}")
        print(f"Reports       : {REPORTS_DIR}")
        print(f"Account file  : {account_path.name}")
        print(f"M5 file       : {m5_path.name}")
        print(f"M15 file      : {m15_path.name}")
        print(f"Health file   : {health_path.name}")
        print("LIVE TRADING  : DISABLED (including demo orders)")
        print("AI MODE       : SHADOW (never affects trades)")
    except Exception as exc:
        reporter.append_health_event({
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "status": "ERROR", "error": str(exc),
        })
        raise
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
