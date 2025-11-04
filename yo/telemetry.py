"""Telemetry helpers for test and dependency insight."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Sequence

LOGS_DIR = Path("data/logs")
SUMMARY_PATH = LOGS_DIR / "test_summary.json"
HISTORY_PATH = LOGS_DIR / "test_history.json"
DEPENDENCY_HISTORY_PATH = LOGS_DIR / "dependency_history.json"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_test_summary() -> Dict[str, Any]:
    data = _read_json(SUMMARY_PATH)
    return data if isinstance(data, dict) else {}


def load_test_history(limit: int | None = None) -> List[Dict[str, Any]]:
    data = _read_json(HISTORY_PATH)
    if not isinstance(data, list):
        return []
    entries = [entry for entry in data if isinstance(entry, dict)]
    if limit is not None and limit >= 0:
        return entries[-limit:]
    return entries


def load_dependency_history(limit: int | None = None) -> List[Dict[str, Any]]:
    data = _read_json(DEPENDENCY_HISTORY_PATH)
    if not isinstance(data, list):
        return []
    entries = [entry for entry in data if isinstance(entry, dict)]
    if limit is not None and limit >= 0:
        return entries[-limit:]
    return entries


def compute_trend(entries: Sequence[Dict[str, Any]], days: int = 7) -> List[Dict[str, Any]]:
    """Return a trend of recent runs (max `days`)."""

    trend: List[Dict[str, Any]] = []
    for entry in entries[-days:]:
        timestamp = entry.get("timestamp")
        try:
            dt = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else None
        except ValueError:
            dt = None

        pass_rate = entry.get("pass_rate")
        if isinstance(pass_rate, (int, float)):
            pass_rate_value = float(pass_rate) * (100 if pass_rate <= 1 else 1)
        else:
            pass_rate_value = None

        trend.append(
            {
                "timestamp": timestamp,
                "status": entry.get("status"),
                "duration_seconds": entry.get("duration_seconds"),
                "pass_rate_percent": pass_rate_value,
                "tests_failed": entry.get("tests_failed", 0),
                "tests_total": entry.get("tests_total", 0),
            }
        )
    return trend


def summarize_failures(history: Sequence[Dict[str, Any]], window: int = 5) -> Dict[str, Any]:
    recent = history[-window:] if window > 0 else list(history)
    failures = [entry for entry in recent if entry.get("tests_failed")]
    missing = set()
    for entry in recent:
        modules = entry.get("missing_modules") or []
        for module in modules:
            missing.add(module)

    durations = [
        float(entry.get("duration_seconds"))
        for entry in recent
        if isinstance(entry.get("duration_seconds"), (int, float))
    ]
    duration_avg = mean(durations) if durations else None

    return {
        "recent_failures": failures,
        "missing_modules": sorted(missing),
        "average_duration": duration_avg,
        "window": len(recent),
    }


__all__ = [
    "load_test_summary",
    "load_test_history",
    "load_dependency_history",
    "compute_trend",
    "summarize_failures",
]
