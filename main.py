from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import MetaTrader5 as mt5
from dotenv import load_dotenv

from ai.shadow import AIShadowEvaluator
from broker.mt5_client import MT5Client
from config import (
    ASIAN_END_HOUR,
    ASIAN_START_HOUR,
    LONDON_END_HOUR,
    LONDON_START_HOUR,
    M15_H1_PIVOT_SPAN,
    M15_MIN_REWARD_R,
    M15_STOP_BUFFER_FRACTION,
    M5_BARS,
    REPORTS_DIR,
    SYMBOL_HINT,
)
from reporting.reporter import Reporter
from reporting.signal_reporter import SignalReporter
from strategies import StrategyRegistry


def main() -> None:
    load_dotenv()

    session_values = [
        ASIAN_START_HOUR,
        ASIAN_END_HOUR,
        LONDON_START_HOUR,
        LONDON_END_HOUR,
    ]
    if any(v is None for v in session_values):
        raise RuntimeError(
            "M15 Sweep & Flip requires explicit session hours. Set "
            "GOLD_AI_ASIAN_START_HOUR, GOLD_AI_ASIAN_END_HOUR, "
            "GOLD_AI_LONDON_START_HOUR and GOLD_AI_LONDON_END_HOUR."
        )

    reporter = Reporter(REPORTS_DIR)
    signal_reporter = SignalReporter(REPORTS_DIR)
    client = MT5Client(SYMBOL_HINT)
    registry = StrategyRegistry(
        asian_start_hour=ASIAN_START_HOUR,
        asian_end_hour=ASIAN_END_HOUR,
        london_start_hour=LONDON_START_HOUR,
        london_end_hour=LONDON_END_HOUR,
        h1_pivot_span=M15_H1_PIVOT_SPAN,
        stop_buffer_fraction=M15_STOP_BUFFER_FRACTION,
        minimum_reward_r=M15_MIN_REWARD_R,
    )
    evaluator = AIShadowEvaluator(REPORTS_DIR)

    try:
        status = client.connect()
        account = client.account_snapshot()
        m5 = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
        reporter.save_account_snapshot(account)
        reporter.save_candles(m5, "m5")

        signals = registry.scan(m5)
        signal_reporter.append(signals)

        ai_results = []
        context = m5.iloc[-13:-1][["time","open","high","low","close"]].to_dict("records")
        for signal in signals:
            ai_results.append(
                evaluator.evaluate_and_log(
                    {"symbol": client.symbol, "signal": asdict(signal), "recent_m5": context}
                )
            )

        reporter.append_health_event({
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "status": "OK",
            "symbol": client.symbol,
            "account_login": status.account_login,
            "server": status.account_server,
            "strategy_models": "|".join(registry.strategy_ids),
            "signals": len(signals),
            "ai_evaluations": len(ai_results),
        })

        print("GOLD_AI — M15 SWEEP & FLIP RESEARCH SCANNER")
        print(f"Account       : {status.account_login} @ {status.account_server}")
        print(f"Symbol        : {client.symbol}")
        print(f"Strategy      : {', '.join(registry.strategy_ids)}")
        print(
            f"Sessions      : Asian {ASIAN_START_HOUR:02d}:00-{ASIAN_END_HOUR:02d}:00 | "
            f"London {LONDON_START_HOUR:02d}:00-{LONDON_END_HOUR:02d}:00"
        )
        print(f"Signals       : {len(signals)}")
        print("LIVE TRADING  : DISABLED")
        print("AI MODE       : SHADOW")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
