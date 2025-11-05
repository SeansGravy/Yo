"""Telemetry helpers for test and dependency insight."""
from __future__ import annotations

import gzip
import json
import re
from datetime import datetime, timedelta
import os
import subprocess
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Sequence, Tuple

LOGS_DIR = Path("data/logs")
SUMMARY_PATH = LOGS_DIR / "test_summary.json"
HISTORY_PATH = LOGS_DIR / "test_history.json"
DEPENDENCY_HISTORY_PATH = LOGS_DIR / "dependency_history.json"
TELEMETRY_SUMMARY_PATH = LOGS_DIR / "telemetry_summary.json"
ARCHIVE_DIR = LOGS_DIR / "telemetry_archive"
SNAPSHOT_DIR = Path("data/snapshots")


def _run_git_command(args: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


def _resolve_git_metadata() -> Tuple[str, str]:
    version = os.environ.get("YO_VERSION")
    commit = os.environ.get("YO_COMMIT")
    if not version:
        version = _run_git_command(["describe", "--tags", "--abbrev=0"]) or "v0.0.0-dev"
    if not commit:
        commit = _run_git_command(["rev-parse", "HEAD"]) or "unknown"
    return version, commit


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

    version, commit = _resolve_git_metadata()
    summary["version"] = version
    summary["commit"] = commit

    if not history:
        _write_json(TELEMETRY_SUMMARY_PATH, summary)
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

    # health score heuristic
    health = compute_health_score(history, summary)
    summary["health_score"] = health

    _write_json(TELEMETRY_SUMMARY_PATH, summary)
    return summary


def load_telemetry_summary() -> Dict[str, Any]:
    data = _read_json(TELEMETRY_SUMMARY_PATH)
    return data if isinstance(data, dict) else {}


def compute_health_score(history: Sequence[Dict[str, Any]], summary: Dict[str, Any] | None = None) -> float:
    if summary is None:
        summary = build_telemetry_summary()

    if not history:
        return 100.0

    pass_rates = [entry.get("pass_rate") for entry in history if isinstance(entry.get("pass_rate"), (int, float))]
    avg_rate = mean(pass_rates) if pass_rates else 1.0
    volatility = pstdev(pass_rates) if len(pass_rates) > 1 else 0.0

    durations = [entry.get("duration_seconds") for entry in history if isinstance(entry.get("duration_seconds"), (int, float))]
    duration_avg = mean(durations) if durations else 0.0

    drift_events = 0
    dependency_history = load_dependency_history(limit=50)
    for event in dependency_history:
        if event.get("action") in {"drift", "repair", "sync"}:
            drift_events += 1

    score = avg_rate * 100
    score -= min(volatility * 100, 20)
    if duration_avg and duration_avg > 10:
        score -= min((duration_avg - 10) * 1.5, 15)
    score -= min(drift_events * 2, 20)

    if summary:
        recurring = summary.get("recurring_errors") or []
        score -= min(len(recurring) * 3, 15)

    return float(max(0.0, min(100.0, score)))


def archive_telemetry() -> Path | None:
    """Persist the latest telemetry summary into the archive."""

    summary = build_telemetry_summary()
    if not summary:
        return None

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = summary.get("latest", {}).get("timestamp")
    try:
        dt = datetime.fromisoformat(ts) if isinstance(ts, str) else datetime.utcnow()
    except ValueError:
        dt = datetime.utcnow()

    archive_path = ARCHIVE_DIR / f"telemetry_{dt.date().isoformat().replace('-', '')}.json"
    _write_json(archive_path, summary)

    compress_before = datetime.utcnow() - timedelta(days=7)
    for json_path in ARCHIVE_DIR.glob("telemetry_*.json"):
        if json_path == archive_path:
            continue
        try:
            dt_string = json_path.stem.split("_")[1]
            file_date = datetime.strptime(dt_string, "%Y%m%d")
        except Exception:
            continue
        if file_date < compress_before:
            gz_path = json_path.with_suffix(".json.gz")
            if not gz_path.exists():
                with gzip.open(gz_path, "wt", encoding="utf-8") as gz:
                    gz.write(json_path.read_text(encoding="utf-8"))
            json_path.unlink(missing_ok=True)

    return archive_path


def list_archives(limit: int | None = None) -> List[Path]:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(ARCHIVE_DIR.glob("telemetry_*.json*"))
    if limit is not None and limit >= 0:
        return files[-limit:]
    return files


__all__ = [
    "load_test_summary",
    "load_test_history",
    "load_dependency_history",
    "compute_trend",
    "summarize_failures",
    "build_telemetry_summary",
    "load_telemetry_summary",
    "archive_telemetry",
    "list_archives",
    "compute_health_score",
]
