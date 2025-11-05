from __future__ import annotations

import json
from pathlib import Path

import pytest

from datetime import timedelta

from yo import metrics


def test_record_metric_and_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "metrics.jsonl"
    monkeypatch.setattr(metrics, "METRICS_PATH", target)

    metrics.record_metric("verify", duration_seconds=10.0, pass_rate=0.9, tests_total=5, tests_passed=5)
    metrics.record_metric("verify", duration_seconds=20.0, pass_rate=0.95, tests_total=5, tests_passed=5)
    metrics.record_metric("chat", latency_seconds=3.0, tokens=100, stream=True)

    entries = metrics.load_metrics()
    summary = metrics.summarize_metrics(entries)

    verify_stats = summary["types"]["verify"]
    assert verify_stats["count"] == 2
    duration_stats = verify_stats["fields"]["duration_seconds"]
    assert duration_stats["avg"] == pytest.approx(15.0)
    assert duration_stats["min"] == pytest.approx(10.0)
    assert duration_stats["max"] == pytest.approx(20.0)

    chat_stats = summary["types"]["chat"]
    assert chat_stats["count"] == 1
    assert chat_stats["fields"]["latency_seconds"]["avg"] == pytest.approx(3.0)
def test_parse_since_window() -> None:
    assert metrics.parse_since_window("30m") == timedelta(minutes=30)
    assert metrics.parse_since_window("2h") == timedelta(hours=2)
    with pytest.raises(ValueError):
        metrics.parse_since_window("invalid")
