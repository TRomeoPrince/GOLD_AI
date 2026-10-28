"""Desired trading state is independent of temporary connection availability."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time


class TemporaryConnectionError(RuntimeError):
    pass


class SafetyStop(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    interval: float = 5
    cap: float = 30
    alert_after: int = 5
    alert_cooldown: float = 300

    @classmethod
    def load(cls):
        values = {}
        path = Path(os.getenv("GOLD_AI_STATE_DIR", str(Path.cwd() / "server"))) / "workspace_settings.json"
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        def number(key, env, default, low, high):
            try:
                return min(high, max(low, float(os.getenv(env, values.get(key, default)))))
            except (TypeError, ValueError):
                return default
        base = number("retry_interval", "GOLD_AI_RETRY_INTERVAL", 5, 1, 300)
        return cls(base, max(base, number("retry_cap", "GOLD_AI_RETRY_CAP", 30, 1, 1800)),
                   int(number("retries_before_alert", "GOLD_AI_RETRIES_BEFORE_ALERT", 5, 1, 100)),
                   number("alert_cooldown", "GOLD_AI_ALERT_COOLDOWN", 300, 10, 86400))


class RetryState:
    def __init__(self, policy=None):
        self.policy = policy or RetryPolicy.load()
        self.failures = 0
        self.last_alert = float("-inf")

    def failed(self):
        self.failures += 1
        return min(self.policy.interval * 2 ** min(self.failures - 1, 20), self.policy.cap)

    @property
    def state(self):
        return "DEGRADED" if self.failures >= self.policy.alert_after else "RECONNECTING"

    def should_alert(self, now=None):
        now = time.monotonic() if now is None else now
        if self.failures >= self.policy.alert_after and now - self.last_alert >= self.policy.alert_cooldown:
            self.last_alert = now
            return True
        return False

    def recovered(self):
        had_failures = self.failures > 0
        self.failures = 0
        return had_failures
