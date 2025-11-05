"""Usage analytics helpers for Yo."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from yo.logging_utils import get_logger

LOGGER = get_logger(__name__)

ANALYTICS_PATH = Path("data/logs/analytics.jsonl")
ANALYTICS_ENV_FLAG = os.environ.get("YO_ANALYTICS", "on").lower()


def analytics_enabled() -> bool:
    return ANALYTICS_ENV_FLAG not in {"0", "off", "false", "disabled"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_entry(entry: Mapping[str, Any]) -> None:
    if not analytics_enabled():
        return
    ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ANALYTICS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(entry)) + "\n")
    except OSError as exc:  # pragma: no cover - filesystem failure
        LOGGER.warning("Unable to append analytics entry: %s", exc)


def record_cli_command(
    command: str,
    *,
    duration_seconds: float | None = None,
    namespace: str | None = None,
    success: bool = True,
    flags: Mapping[str, Any] | None = None,
) -> None:
    payload: Dict[str, Any] = {
        "timestamp": _utc_now().isoformat().replace("+00:00", "Z"),
        "type": "cli",
        "command": command,
        "success": bool(success),
    }
    if duration_seconds is not None:
        payload["duration_seconds"] = round(float(duration_seconds), 3)
    if namespace:
        payload["namespace"] = namespace
    if flags:
        payload["flags"] = {key: value for key, value in flags.items() if isinstance(key, str)}
    _write_entry(payload)


def record_chat_interaction(
    session_id: str,
    *,
    namespace: str,
    latency_seconds: float,
    tokens: int,
    stream: bool,
    history_length: int,
    fallback: bool,
    first_token_latency_ms: float | None,
) -> None:
    payload = {
        "timestamp": _utc_now().isoformat().replace("+00:00", "Z"),
        "type": "chat",
        "session_id": session_id,
        "namespace": namespace,
        "latency_seconds": round(float(latency_seconds), 3),
        "tokens": int(tokens),
        "stream": bool(stream),
        "turns": int(history_length),
        "fallback": bool(fallback),
    }
    if first_token_latency_ms is not None:
        payload["first_token_latency_ms"] = round(float(first_token_latency_ms), 2)
    _write_entry(payload)


def record_ingest_event(
    *,
    namespace: str,
    documents: int,
    chunks: int,
    duration_seconds: float,
) -> None:
    payload = {
        "timestamp": _utc_now().isoformat().replace("+00:00", "Z"),
        "type": "ingest",
        "namespace": namespace,
        "documents": int(documents),
        "chunks": int(chunks),
        "duration_seconds": round(float(duration_seconds), 3),
    }
    _write_entry(payload)


def load_analytics(*, since: timedelta | None = None) -> List[Dict[str, Any]]:
    if not ANALYTICS_PATH.exists():
        return []
    cutoff: Optional[datetime] = _utc_now() - since if since else None
    entries: List[Dict[str, Any]] = []
    try:
        with ANALYTICS_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cutoff:
                    try:
                        timestamp = datetime.fromisoformat(payload.get("timestamp", "").replace("Z", "+00:00"))
                    except ValueError:
                        timestamp = None
                    if timestamp and timestamp < cutoff:
                        continue
                entries.append(payload)
    except OSError as exc:  # pragma: no cover
        LOGGER.warning("Unable to read analytics log: %s", exc)
    return entries


def summarize_usage(entries: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    entries = list(entries)
    commands = Counter()
    namespaces = Counter()
    chat_sessions = Counter()
    chat_latency: List[float] = []
    chat_tokens: List[int] = []
    chat_first_token: List[float] = []
    chat_fallbacks = 0
    ingest_counts = Counter()
    ingest_duration: List[float] = []

    for entry in entries:
        entry_type = entry.get("type")
        if entry_type == "cli":
            commands[entry.get("command", "unknown")] += 1
            if entry.get("namespace"):
                namespaces[str(entry["namespace"])] += 1
        elif entry_type == "chat":
            chat_sessions[entry.get("namespace", "default")] += 1
            if isinstance(entry.get("latency_seconds"), (int, float)):
                chat_latency.append(float(entry["latency_seconds"]))
            if isinstance(entry.get("tokens"), (int, float)):
                chat_tokens.append(int(entry["tokens"]))
            if isinstance(entry.get("first_token_latency_ms"), (int, float)):
                chat_first_token.append(float(entry["first_token_latency_ms"]))
            if entry.get("fallback"):
                chat_fallbacks += 1
        elif entry_type == "ingest":
            ingest_counts[entry.get("namespace", "default")] += 1
            if isinstance(entry.get("duration_seconds"), (int, float)):
                ingest_duration.append(float(entry["duration_seconds"]))

    def _average(values: Iterable[float]) -> float | None:
        seq = list(values)
        if not seq:
            return None
        return sum(seq) / len(seq)

    return {
        "commands": commands.most_common(),
        "namespaces": namespaces.most_common(),
        "chat": {
            "total_sessions": sum(chat_sessions.values()),
            "by_namespace": chat_sessions.most_common(),
            "avg_latency_seconds": _average(chat_latency),
            "avg_tokens": _average(chat_tokens),
            "avg_first_token_latency_ms": _average(chat_first_token),
            "fallback_count": chat_fallbacks,
        },
        "ingest": {
            "total_runs": sum(ingest_counts.values()),
            "by_namespace": ingest_counts.most_common(),
            "avg_duration_seconds": _average(ingest_duration),
        },
        "total": len(entries),
    }


__all__ = [
    "ANALYTICS_PATH",
    "analytics_enabled",
    "record_cli_command",
    "record_chat_interaction",
    "record_ingest_event",
    "load_analytics",
    "summarize_usage",
]
