"""Lightweight metrics aggregation and summarisation utilities for Yo."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from yo.logging_utils import get_logger

LOGGER = get_logger(__name__)

METRICS_PATH = Path("data/logs/metrics.jsonl")
PROCESS_START = datetime.now(timezone.utc)
SINCE_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[smhdw])$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalise_timestamp(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def parse_since_window(value: str | None) -> timedelta | None:
    if not value:
        return None
    token = value.strip().lower()
    match = SINCE_PATTERN.match(token)
    if not match:
        raise ValueError("Duration must use forms such as '30m', '24h', '7d', or '2w'.")
    amount = int(match.group("value"))
    unit = match.group("unit")
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "w":
        return timedelta(weeks=amount)
    raise ValueError(f"Unsupported duration unit '{unit}'.")


def record_metric(metric_type: str, **fields: Any) -> Dict[str, Any]:
    """Append a metrics sample to ``metrics.jsonl``."""

    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_now().isoformat().replace("+00:00", "Z")
    entry: Dict[str, Any] = {"timestamp": timestamp, "type": metric_type}
    entry.update(fields)
    try:
        with METRICS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError as exc:  # pragma: no cover - filesystem failure
        LOGGER.warning("Unable to write metrics entry: %s", exc)
    return entry


def load_metrics(*, since: timedelta | None = None) -> List[Dict[str, Any]]:
    """Load metrics entries, optionally filtering by ``since`` window."""

    if not METRICS_PATH.exists():
        return []
    entries: List[Dict[str, Any]] = []
    cutoff: datetime | None = None
    if since:
        cutoff = _utc_now() - since
    try:
        with METRICS_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cutoff:
                    ts = _normalise_timestamp(payload.get("timestamp"))
                    if ts and ts < cutoff:
                        continue
                entries.append(payload)
    except OSError as exc:  # pragma: no cover - filesystem failure
        LOGGER.warning("Unable to read metrics log: %s", exc)
    return entries


def _aggregate_numeric(values: Iterable[float]) -> Tuple[float | None, float | None, float | None]:
    seq = list(values)
    if not seq:
        return None, None, None
    minimum = min(seq)
    maximum = max(seq)
    average = sum(seq) / len(seq)
    return minimum, maximum, average


def summarize_metrics(entries: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Produce per-metric statistics for the provided entries."""

    per_type: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        metric_type = str(entry.get("type") or "unknown")
        bucket = per_type.setdefault(
            metric_type,
            {
                "count": 0,
                "fields": defaultdict(lambda: {"count": 0, "values": []}),
                "latest": None,
            },
        )
        bucket["count"] += 1
        timestamp = _normalise_timestamp(entry.get("timestamp"))
        if timestamp:
            existing = bucket["latest"]
            if not existing or _normalise_timestamp(existing.get("timestamp")) < timestamp:
                bucket["latest"] = dict(entry)
        for key, value in entry.items():
            if key in {"timestamp", "type"}:
                continue
            if isinstance(value, (int, float)):
                numeric = float(value)
                field_stats = bucket["fields"][key]
                field_stats["count"] += 1
                field_stats["values"].append(numeric)

    summary: Dict[str, Any] = {
        "types": {},
        "total": 0,
        "uptime_seconds": (_utc_now() - PROCESS_START).total_seconds(),
    }

    for metric_type, data in per_type.items():
        summary["total"] += data["count"]
        fields_summary: Dict[str, Any] = {}
        for field, stats in data["fields"].items():
            minimum, maximum, average = _aggregate_numeric(stats["values"])
            fields_summary[field] = {
                "count": stats["count"],
                "min": minimum,
                "max": maximum,
                "avg": average,
            }
        summary["types"][metric_type] = {
            "count": data["count"],
            "fields": fields_summary,
            "latest": data["latest"],
        }
    return summary


def summarize_since(window: str | None) -> Dict[str, Any]:
    """Convenience helper to summarise metrics for ``window``."""

    since = parse_since_window(window) if window else None
    entries = load_metrics(since=since)
    payload = summarize_metrics(entries)
    payload["window"] = window or "all"
    return payload


__all__ = [
    "METRICS_PATH",
    "parse_since_window",
    "record_metric",
    "load_metrics",
    "summarize_metrics",
    "summarize_since",
]
