from __future__ import annotations

import os
from pathlib import Path

import pytest

from yo import optimizer


def test_generate_recommendations_from_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YO_CHUNK_SIZE", raising=False)
    metrics_entries = [
        {"type": "ingest", "duration_seconds": 120.0, "chunks_ingested": 200},
        {"type": "chat", "latency_seconds": 6.0, "tokens": 120, "stream": True, "history_length": 1},
    ]
    analytics_entries: list[dict[str, object]] = []
    recs = optimizer.generate_recommendations(metrics_entries=metrics_entries, analytics_entries=analytics_entries)
    ids = {rec.get("id") for rec in recs}
    assert "ingest_chunk_tuning" in ids
    assert "chat_stream_fallback" in ids


def test_apply_recommendations_updates_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    history_path = tmp_path / "optimizer.jsonl"
    monkeypatch.setattr(optimizer, "OPTIMIZER_HISTORY_PATH", history_path)
    recs = [
        {
            "id": "test",
            "title": "Set test key",
            "action": "env_update",
            "env": {"TEST_KEY": "value"},
        }
    ]

    applied = optimizer.apply_recommendations(recs, env_file=env_path, auto_only=False)
    assert env_path.exists()
    contents = env_path.read_text(encoding="utf-8")
    assert "TEST_KEY='value'" in contents or 'TEST_KEY="value"' in contents
    assert applied
    history_entries = history_path.read_text(encoding="utf-8").strip().splitlines()
    assert history_entries
