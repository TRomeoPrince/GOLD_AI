"""Independent Gemini shadow analysis; never controls order execution."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class AIShadowDecision:
    mode: str = "SHADOW"
    decision: str = "NOT_EVALUATED"
    confidence: float = 0.0
    reason: str = "No evaluation requested."
    model: str = ""
    error: str = ""


class AIShadowEvaluator:
    """Research only. Failures never change deterministic strategy signals."""

    def __init__(self, reports_dir: Path | str = "Reports"):
        self.path = Path(reports_dir) / "ai_shadow_decisions.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.api_key = os.getenv("GEMINI_API_KEY", "")

    def evaluate(self, setup: dict) -> AIShadowDecision:
        if not self.api_key:
            return AIShadowDecision(reason="GEMINI_API_KEY missing; baseline unchanged.", model=self.model)
        prompt = (
            "You are a trading setup research reviewer. Never place trades. "
            "Assess only the provided XAUUSD M5 setup and recent OHLC context. "
            "Do not invent missing market/news facts. Respond with a JSON object: "
            '{"decision":"ALLOW or REJECT or UNCERTAIN","confidence":0.0,"reason":"short explanation"}. '
            "Confidence is subjective, not a calibrated probability.\n"
            + json.dumps(setup, default=str, separators=(",", ":"))
        )
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
        }).encode("utf-8")
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" + self.model + ":generateContent"
        req = urllib.request.Request(endpoint, data=body, headers={
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                raw = json.load(response)
            text = raw["candidates"][0]["content"]["parts"][0]["text"]
            obj = json.loads(text)
            decision = str(obj.get("decision", "UNCERTAIN")).upper()
            if decision not in ("ALLOW", "REJECT", "UNCERTAIN"):
                decision = "UNCERTAIN"
            confidence = max(0.0, min(1.0, float(obj.get("confidence", 0))))
            result = AIShadowDecision(decision=decision, confidence=confidence,
                                      reason=str(obj.get("reason", ""))[:500], model=self.model)
        except Exception as exc:
            result = AIShadowDecision(decision="ERROR", reason="AI request failed; baseline unchanged.",
                                      model=self.model, error=str(exc)[:250])
        return result

    def evaluate_and_log(self, setup: dict) -> AIShadowDecision:
        result = self.evaluate(setup)
        row = {"time_utc": datetime.now(timezone.utc).isoformat(), "setup": setup,
               "ai": asdict(result)}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str, separators=(",", ":")) + "\n")
        return result
