from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

import MetaTrader5 as mt5
from dotenv import load_dotenv

from ai.shadow import AIShadowEvaluator
from broker.mt5_client import MT5Client
from config import (
    ACTIVE_MARKETS,
    ASIAN_END_HOUR,
    ASIAN_START_HOUR,
    LONDON_END_HOUR,
    LONDON_START_HOUR,
    M15_H1_PIVOT_SPAN,
    M15_MIN_REWARD_R,
    M15_STOP_BUFFER_FRACTION,
    M5_BARS,
    REPORTS_DIR,
)
from reporting.reporter import Reporter
from reporting.signal_reporter import SignalReporter
from strategies import StrategyRegistry


def _registry_for_market(market: str) -> StrategyRegistry:
    if market.upper() in {"US30", "US30.CASH", "US30.STD"}:
        session_values = [
            ASIAN_START_HOUR,
            ASIAN_END_HOUR,
            LONDON_START_HOUR,
            LONDON_END_HOUR,
        ]
        if any(v is None for v in session_values):
            raise RuntimeError(
                "US30 M15 Sweep & Flip requires explicit session hours. Set "
                "GOLD_AI_ASIAN_START_HOUR, GOLD_AI_ASIAN_END_HOUR, "
                "GOLD_AI_LONDON_START_HOUR and GOLD_AI_LONDON_END_HOUR."
            )
        return StrategyRegistry(
            market=market,
            asian_start_hour=ASIAN_START_HOUR,
            asian_end_hour=ASIAN_END_HOUR,
            london_start_hour=LONDON_START_HOUR,
            london_end_hour=LONDON_END_HOUR,
            h1_pivot_span=M15_H1_PIVOT_SPAN,
            stop_buffer_fraction=M15_STOP_BUFFER_FRACTION,
            minimum_reward_r=M15_MIN_REWARD_R,
        )
    return StrategyRegistry(market=market)


def main() -> None:
    load_dotenv()

    if not ACTIVE_MARKETS:
        raise RuntimeError("No markets configured.")

    reporter = Reporter(REPORTS_DIR)
    signal_reporter = SignalReporter(REPORTS_DIR)
    evaluator = AIShadowEvaluator(REPORTS_DIR)

    total_signals = 0
    try:
        for market, hint in ACTIVE_MARKETS.items():
            client = MT5Client(hint)
            status = client.connect()
            account = client.account_snapshot()
            m5 = client.candles(mt5.TIMEFRAME_M5, M5_BARS)
            registry = _registry_for_market(market)

            reporter.save_account_snapshot(account)
            reporter.save_candles(m5, f"{market.lower()}_m5")

            signals = registry.scan(m5)
            total_signals += len(signals)
            signal_reporter.append(signals)

            context = m5.iloc[-13:-1][["time","open","high","low","close"]].to_dict("records")
            for signal in signals:
                evaluator.evaluate_and_log({
                    "market": market,
                    "symbol": client.symbol,
                    "signal": asdict(signal),
                    "recent_m5": context,
                })

            reporter.append_health_event({
                "time_utc": datetime.now(timezone.utc).isoformat(),
                "status": "OK",
                "market": market,
                "symbol": client.symbol,
                "account_login": status.account_login,
                "server": status.account_server,
                "strategy_models": "|".join(registry.strategy_ids),
                "signals": len(signals),
                "ai_provider": "GROQ",
                "ai_model": evaluator.model,
            })

            print(
                f"{market}: {client.symbol} | "
                f"{', '.join(registry.strategy_ids) or 'NO STRATEGY'} | "
                f"signals={len(signals)}"
            )

        print("GOLD_AI — CURRENT RESEARCH SCANNER")
        print("Gold         : refined SUPPORT_RESISTANCE")
        print("US30         : M15_SWEEP_FLIP")
        print(f"Total signals: {total_signals}")
        print(
            f"AI SHADOW    : GROQ {evaluator.model} / "
            + ("CONFIGURED" if evaluator.api_key else "KEY MISSING")
        )
        print("LIVE TRADING : DISABLED")
    finally:
        MT5Client.shutdown()


if __name__ == "__main__":
    main()
