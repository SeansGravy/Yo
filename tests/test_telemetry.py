from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from yo import telemetry


def _configure_temp_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(telemetry, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(telemetry, "SUMMARY_PATH", tmp_path / "test_summary.json")
    monkeypatch.setattr(telemetry, "HISTORY_PATH", tmp_path / "test_history.json")
    monkeypatch.setattr(telemetry, "DEPENDENCY_HISTORY_PATH", tmp_path / "dependency_history.json")
    monkeypatch.setattr(telemetry, "TELEMETRY_SUMMARY_PATH", tmp_path / "telemetry_summary.json")
    monkeypatch.setattr(telemetry, "ARCHIVE_DIR", tmp_path / "telemetry_archive")
    monkeypatch.setattr(telemetry, "_resolve_git_metadata", lambda: ("v-test", "abcdef123"))


def test_archive_telemetry_creates_archive_and_compresses_old(tmp_path, monkeypatch) -> None:
    _configure_temp_logs(monkeypatch, tmp_path)

    telemetry.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    telemetry.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    old_archive = telemetry.ARCHIVE_DIR / "telemetry_20200101.json"
    old_archive.write_text(json.dumps({"latest": {"timestamp": "2020-01-01T00:00:00"}}), encoding="utf-8")

    summary_payload = {
        "timestamp": "2025-11-05T00:00:00",
        "status": "✅ Verify successful",
        "tests_total": 10,
        "tests_passed": 10,
        "duration_seconds": 8.0,
        "pass_rate": 1.0,
    }
    telemetry.SUMMARY_PATH.write_text(json.dumps(summary_payload), encoding="utf-8")

    history_payload = [
        {
            "timestamp": "2025-11-04T00:00:00",
            "status": "✅ Verify successful",
            "tests_total": 10,
            "tests_passed": 10,
            "duration_seconds": 9.0,
            "pass_rate": 1.0,
        },
        {
            "timestamp": "2025-11-05T00:00:00",
            "status": "✅ Verify successful",
            "tests_total": 10,
            "tests_passed": 10,
            "duration_seconds": 8.0,
            "pass_rate": 1.0,
        },
    ]
    telemetry.HISTORY_PATH.write_text(json.dumps(history_payload), encoding="utf-8")
    telemetry.DEPENDENCY_HISTORY_PATH.write_text("[]", encoding="utf-8")

    archive_path = telemetry.archive_telemetry()
    assert archive_path is not None
    assert archive_path.exists()

    archives = telemetry.list_archives()
    assert archive_path in archives

    compressed_old = old_archive.with_suffix(".json.gz")
    assert compressed_old.exists()
    with gzip.open(compressed_old, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["latest"]["timestamp"] == "2020-01-01T00:00:00"


def test_compute_health_score_penalizes_volatility_and_drift(monkeypatch) -> None:
    monkeypatch.setattr(
        telemetry,
        "load_dependency_history",
        lambda limit=50: [
            {"action": "drift", "packages": ["pkgA"]},
            {"action": "sync", "packages": ["pkgB"]},
        ],
    )

    history = [
        {"pass_rate": 1.0, "duration_seconds": 9.0},
        {"pass_rate": 0.8, "duration_seconds": 11.0},
    ]
    summary = {"recurring_errors": [{"message": "ImportError", "count": 2}]}

    score = telemetry.compute_health_score(history, summary)
    assert pytest.approx(score, rel=1e-3) == 73.0
