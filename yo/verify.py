"""Helpers for Yo verification workflows."""
from __future__ import annotations

import datetime
import json
import os
from typing import Any


def write_test_summary(result: str = "✅ Verify successful", **extra: Any) -> None:
    """Persist a lightweight summary of the latest verification run."""

    os.makedirs("data/logs", exist_ok=True)
    summary = {
        "timestamp": datetime.datetime.now().isoformat(),
        "status": result,
    }
    if extra:
        summary.update(extra)

    path = "data/logs/test_summary.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(f"[Yo] Test summary written: {summary['timestamp']} -> {path}")


__all__ = ["write_test_summary"]
