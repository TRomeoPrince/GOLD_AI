from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd


class SignalReporter:
    def __init__(self, reports_dir: Path) -> None:
        self.path = reports_dir / "strategy_signals.csv"

    def append(self, signals) -> None:
        if not signals:
            return
        rows = []
        for signal in signals:
            row = asdict(signal)
            row["features"] = repr(row["features"])
            rows.append(row)
        pd.DataFrame(rows).to_csv(
            self.path, mode="a", header=not self.path.exists(), index=False
        )
