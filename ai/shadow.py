"""Independent Groq shadow analysis; never controls order execution."""
from __future__ import annotations

import json
import os
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
    provider: str = "GROQ"
    error: str = ""


class AIShadowEvaluator:
    """Research only. AI can never add, remove, modify, or veto trades."""

    def __init__(self, reports_dir: Path | str = "Reports"):
        self.path = Path(reports_dir) / "ai_shadow_decisions.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"

    def evaluate(self, setup: dict) -> AIShadowDecision:
        if not self.api_key:
            return AIShadowDecision(
                reason="GROQ_API_KEY missing; deterministic strategy unchanged.",
                model=self.model,
            )

        prompt = (
            "You are a trading setup research reviewer operating in SHADOW mode only. "
            "Never place, cancel, resize, or modify trades. Assess only the supplied "
            "deterministic strategy signal and recent OHLC context. Do not invent "
            "market news, fundamentals, or missing facts. Return JSON only with keys: "
            "decision (ALLOW|REJECT|UNCERTAIN), confidence (0 to 1), reason (short).\n"
            + json.dumps(setup, default=str, separators=(",", ":"))
        )

        body = json.dumps({
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a non-executing trading research classifier. "
                        "Output valid JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                raw = json.load(response)
            text = raw["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.lower().startswith("json"):
                    text = text[4:].strip()
            obj = json.loads(text)

            decision = str(obj.get("decision", "UNCERTAIN")).upper()
            if decision not in ("ALLOW", "REJECT", "UNCERTAIN"):
                decision = "UNCERTAIN"
            confidence = max(0.0, min(1.0, float(obj.get("confidence", 0.0))))
            return AIShadowDecision(
                decision=decision,
                confidence=confidence,
                reason=str(obj.get("reason", ""))[:500],
                model=self.model,
            )
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            return AIShadowDecision(
                decision="ERROR",
                reason="AI request failed; deterministic strategy unchanged.",
                model=self.model,
                error=f"HTTP {exc.code}: {detail[:500]}",
            )
        except Exception as exc:
            return AIShadowDecision(
                decision="ERROR",
                reason="AI request failed; deterministic strategy unchanged.",
                model=self.model,
                error=str(exc)[:500],
            )

    def evaluate_and_log(self, setup: dict) -> AIShadowDecision:
        result = self.evaluate(setup)
        row = {
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "setup": setup,
            "ai": asdict(result),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str, separators=(",", ":")) + "\n")
        return result
