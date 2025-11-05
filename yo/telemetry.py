"""Telemetry helpers for test and dependency insight."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Sequence, Tuple

LOGS_DIR = Path("data/logs")
SUMMARY_PATH = LOGS_DIR / "test_summary.json"
HISTORY_PATH = LOGS_DIR / "test_history.json"
DEPENDENCY_HISTORY_PATH = LOGS_DIR / "dependency_history.json"
TELEMETRY_SUMMARY_PATH = LOGS_DIR / "telemetry_summary.json"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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

    result = {
        "recent_failures": failures,
        "missing_modules": sorted(missing),
        "average_duration": duration_avg,
        "window": len(recent),
    }
    return result


def _group_by_day(entries: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        ts = entry.get("timestamp")
        try:
            dt = datetime.fromisoformat(ts) if isinstance(ts, str) else None
        except ValueError:
            dt = None
        if not dt:
            continue
        day = dt.date().isoformat()
        buckets.setdefault(day, []).append(entry)
    return buckets


def compute_pass_rate_variance(entries: Sequence[Dict[str, Any]], window: int = 10) -> Tuple[float | None, float | None]:
    recent = entries[-window:] if window > 0 else list(entries)
    rates = [entry.get("pass_rate") for entry in recent if isinstance(entry.get("pass_rate"), (int, float))]
    if not rates:
        return None, None
    mean_rate = float(mean(rates))
    volatility = float(pstdev(rates)) if len(rates) > 1 else 0.0
    return mean_rate, volatility


def extract_recurring_errors(log_dir: Path, limit: int = 5) -> List[Tuple[str, int]]:
    pattern = re.compile(r"ModuleNotFoundError: No module named '([^']+)'|ImportError: cannot import name '([^']+)'|ERROR\s+-\s+(.*)")
    counter: Dict[str, int] = {}
    for path in sorted(log_dir.glob("yo_test_results_*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in pattern.finditer(text):
            groups = [g for g in match.groups() if g]
            if not groups:
                continue
            key = groups[0]
            key = key.strip()
            counter[key] = counter.get(key, 0) + 1
    items = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    return items[:limit]


def build_telemetry_summary() -> Dict[str, Any]:
    history = load_test_history()
    summary: Dict[str, Any] = {}
    if not history:
        return summary

    latest = history[-1]
    summary["latest"] = {
        "timestamp": latest.get("timestamp"),
        "status": latest.get("status"),
        "tests_total": latest.get("tests_total"),
        "tests_passed": latest.get("tests_passed"),
        "tests_failed": latest.get("tests_failed"),
        "duration_seconds": latest.get("duration_seconds"),
        "missing_modules": latest.get("missing_modules", []),
    }

    mean_rate, volatility = compute_pass_rate_variance(history, window=10)
    if mean_rate is not None:
        summary["pass_rate_mean"] = mean_rate
    if volatility is not None:
        summary["pass_rate_volatility"] = volatility

    durations = [float(entry.get("duration_seconds")) for entry in history if isinstance(entry.get("duration_seconds"), (int, float))]
    if durations:
        summary["duration_average"] = float(mean(durations))

    by_day = _group_by_day(history)
    daily_stats = []
    for day, entries in sorted(by_day.items(), key=lambda item: item[0], reverse=True):
        daily_durations = [float(entry.get("duration_seconds")) for entry in entries if isinstance(entry.get("duration_seconds"), (int, float))]
        duration_avg = float(mean(daily_durations)) if daily_durations else None
        pass_rates = [float(entry.get("pass_rate")) for entry in entries if isinstance(entry.get("pass_rate"), (int, float))]
        pass_rate_avg = float(mean(pass_rates)) if pass_rates else None
        daily_stats.append(
            {
                "day": day,
                "runs": len(entries),
                "pass_rate": pass_rate_avg,
                "duration_seconds": duration_avg,
            }
        )
    summary["daily_stats"] = daily_stats

    recurring_errors = extract_recurring_errors(LOGS_DIR)
    summary["recurring_errors"] = [
        {"message": message, "count": count}
        for message, count in recurring_errors
    ]

    _write_json(TELEMETRY_SUMMARY_PATH, summary)
    return summary


def load_telemetry_summary() -> Dict[str, Any]:
    data = _read_json(TELEMETRY_SUMMARY_PATH)
    return data if isinstance(data, dict) else {}


__all__ = [
    "load_test_summary",
    "load_test_history",
    "load_dependency_history",
    "compute_trend",
    "summarize_failures",
    "build_telemetry_summary",
    "load_telemetry_summary",
]
