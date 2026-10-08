from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AIShadowDecision:
    mode: str = "SHADOW"
    decision: str = "NOT_EVALUATED"
    confidence: float = 0.0
    reason: str = "AI provider not connected yet."


class AIShadowEvaluator:
    def evaluate(self, setup: dict) -> AIShadowDecision:
        # Placeholder by design. We establish MT5 + reporting first.
        return AIShadowDecision()
