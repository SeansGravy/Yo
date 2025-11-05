"""Self-optimisation helpers for Yo."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from dotenv import set_key

from yo.analytics import load_analytics
from yo.logging_utils import get_logger
from yo.metrics import load_metrics

LOGGER = get_logger(__name__)

OPTIMIZER_HISTORY_PATH = Path("data/logs/optimizer_history.jsonl")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _average(values: Iterable[float]) -> float | None:
    seq = [float(value) for value in values if isinstance(value, (int, float))]
    if not seq:
        return None
    return sum(seq) / len(seq)


def _collect_metric(entries: Iterable[Mapping[str, Any]], metric_type: str) -> List[Mapping[str, Any]]:
    return [entry for entry in entries if entry.get("type") == metric_type]


def generate_recommendations(
    metrics_entries: Sequence[Mapping[str, Any]] | None = None,
    analytics_entries: Sequence[Mapping[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    metrics_entries = list(metrics_entries or load_metrics())
    analytics_entries = list(analytics_entries or load_analytics())

    recommendations: List[Dict[str, Any]] = []

    # Ingestion tuning
    ingest_entries = _collect_metric(metrics_entries, "ingest")
    if ingest_entries:
        per_chunk_timings: List[float] = []
        for entry in ingest_entries:
            duration = entry.get("duration_seconds")
            chunks = entry.get("chunks_ingested") or entry.get("chunks")
            if isinstance(duration, (int, float)) and isinstance(chunks, (int, float)) and chunks > 0:
                per_chunk_timings.append(float(duration) / float(chunks))
        avg_per_chunk = _average(per_chunk_timings)
        current_chunk_size = int(os.environ.get("YO_CHUNK_SIZE", "800") or "800")
        if avg_per_chunk and avg_per_chunk > 0.25 and current_chunk_size >= 700:
            recommendations.append(
                {
                    "id": "ingest_chunk_tuning",
                    "title": "Reduce ingestion chunk size",
                    "detail": f"Average ingestion time per chunk is {avg_per_chunk:.2f}s. "
                    "Reducing chunk size can improve embedding throughput.",
                    "action": "env_update",
                    "env": {
                        "YO_CHUNK_SIZE": "600",
                        "YO_CHUNK_OVERLAP": "90",
                    },
                }
            )

    # Chat streaming fallback
    chat_entries = _collect_metric(metrics_entries, "chat")
    if chat_entries:
        latencies = [float(entry.get("latency_seconds", 0.0)) for entry in chat_entries if isinstance(entry.get("latency_seconds"), (int, float))]
        avg_latency = _average(latencies)
        stream_setting = os.environ.get("YO_CHAT_STREAM_FALLBACK", "auto").lower()
        if avg_latency and avg_latency > 5.0 and stream_setting != "force":
            recommendations.append(
                {
                    "id": "chat_stream_fallback",
                    "title": "Enable chat stream fallback",
                    "detail": f"Average chat latency is {avg_latency:.1f}s. Forcing the fallback mode will return full replies immediately.",
                    "action": "env_update",
                    "env": {"YO_CHAT_STREAM_FALLBACK": "force"},
                }
            )

    # Verification reliability
    verify_entries = _collect_metric(metrics_entries, "verify")
    if verify_entries:
        pass_rates = []
        for entry in verify_entries:
            value = entry.get("pass_rate")
            if isinstance(value, (int, float)):
                pass_rates.append(float(value) if value <= 1 else float(value) / 100.0)
        avg_pass = _average(pass_rates)
        if avg_pass and avg_pass < 0.95:
            recommendations.append(
                {
                    "id": "verify_reliability",
                    "title": "Investigate failing verification runs",
                    "detail": f"Average verification pass rate is {(avg_pass * 100):.1f}%. "
                    "Run `python3 -m yo.cli deps repair` or review dependency drift.",
                    "action": "manual",
                    "next_steps": [
                        "Run `python3 -m yo.cli deps check`",
                        "Review recent failures via `yo explain verify`",
                    ],
                }
            )

    # High verify usage -> offer analytics summary (example using analytics)
    return recommendations


def apply_recommendations(
    recommendations: Iterable[Mapping[str, Any]],
    *,
    env_file: Path | str = Path(".env"),
    auto_only: bool = True,
) -> List[Dict[str, Any]]:
    env_path = Path(env_file)
    applied: List[Dict[str, Any]] = []
    for rec in recommendations:
        action = rec.get("action")
        if action != "env_update":
            if not auto_only:
                LOGGER.info("Skipping non-automatic recommendation: %s", rec.get("title"))
            continue
        env_updates = rec.get("env") or {}
        if not isinstance(env_updates, Mapping):
            continue
        env_path.parent.mkdir(parents=True, exist_ok=True)
        for key, value in env_updates.items():
            set_key(str(env_path), str(key), str(value))
        record = {
            "timestamp": _utc_now(),
            "applied": dict(env_updates),
            "recommendation_id": rec.get("id"),
            "title": rec.get("title"),
        }
        _append_history(record)
        applied.append(record)
    return applied


def _append_history(entry: Mapping[str, Any]) -> None:
    OPTIMIZER_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with OPTIMIZER_HISTORY_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(entry)) + "\n")
    except OSError as exc:  # pragma: no cover
        LOGGER.warning("Unable to append optimizer history: %s", exc)


__all__ = ["generate_recommendations", "apply_recommendations", "OPTIMIZER_HISTORY_PATH"]
