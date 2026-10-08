from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


class Reporter:
    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def save_account_snapshot(self, account: dict) -> Path:
        path = self.reports_dir / "account_snapshot.json"
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            **account,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def save_candles(self, frame: pd.DataFrame, label: str) -> Path:
        path = self.reports_dir / f"{label.lower()}_candles.csv"
        frame.to_csv(path, index=False)
        return path

    def append_health_event(self, event: dict) -> Path:
        path = self.reports_dir / "system_health.csv"
        frame = pd.DataFrame([event])
        frame.to_csv(path, mode="a", header=not path.exists(), index=False)
        return path
