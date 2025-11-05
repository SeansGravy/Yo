from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from yo import cli
from yo.brain import MissingDependencyError


class RecordingBrain:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.switch_calls: list[str] = []
        self.purge_calls: list[str] = []
        self.activity: dict[str, dict[str, object]] = {}
        self.drift: dict[str, dict[str, object]] = {}

    def ingest(self, path: str, namespace: str = "default") -> None:
        self.calls.append((path, namespace))

    def ns_switch(self, namespace: str) -> None:
        self.switch_calls.append(namespace)

    def ns_purge(self, namespace: str) -> None:
        self.purge_calls.append(namespace)

    def namespace_activity(self) -> dict[str, dict[str, object]]:
        return self.activity

    def namespace_drift(self, since) -> dict[str, dict[str, object]]:  # type: ignore[override]
        return self.drift


def test_handle_add_invokes_brain(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_text("content", encoding="utf-8")

    brain = RecordingBrain()
    args = argparse.Namespace(path=str(pdf_path), ns="reports")

    cli._handle_add(args, brain)

    assert brain.calls == [(str(pdf_path), "reports")]


def test_handle_add_reports_missing_dependency(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    xlsx_path = tmp_path / "sheet.xlsx"
    xlsx_path.write_text("placeholder", encoding="utf-8")

    class FailingBrain(RecordingBrain):
        def ingest(self, path: str, namespace: str = "default") -> None:  # type: ignore[override]
            raise MissingDependencyError("Install openpyxl")

    brain = FailingBrain()
    args = argparse.Namespace(path=str(xlsx_path), ns="finance")

    with pytest.raises(SystemExit):
        cli._handle_add(args, brain)

    captured = capsys.readouterr()
    assert "openpyxl" in captured.out
    assert "Install the missing dependency" in captured.out


def test_handle_ns_switch_invokes_brain() -> None:
    brain = RecordingBrain()
    args = argparse.Namespace(name="research", ns=None)

    cli._handle_ns_switch(args, brain)

    assert brain.switch_calls == ["research"]


def test_handle_ns_purge_invokes_brain() -> None:
    brain = RecordingBrain()
    args = argparse.Namespace(name="legacy", ns=None)

    cli._handle_ns_purge(args, brain)

    assert brain.purge_calls == ["legacy"]


def test_handle_ns_stats_outputs_alerts(capsys: pytest.CaptureFixture[str]) -> None:
    brain = RecordingBrain()
    brain.activity = {
        "alpha": {
            "documents": 1500,
            "documents_delta": 200,
            "chunks": 6000,
            "chunks_delta": 400,
            "records": 1200,
            "growth_percent": 80.0,
            "ingest_runs": 5,
            "last_ingested": "2025-01-01T12:00:00",
        }
    }

    previous_console = cli.console
    cli.console = None
    try:
        cli._handle_ns_stats(argparse.Namespace(), brain)
    finally:
        cli.console = previous_console

    output = capsys.readouterr().out
    assert "Namespace Statistics" in output
    assert "Alerts" in output


def test_handle_ns_drift_respects_since_argument(capsys: pytest.CaptureFixture[str]) -> None:
    brain = RecordingBrain()
    brain.drift = {
        "alpha": {
            "documents_added": 50,
            "chunks_added": 75,
            "growth_percent": 25.0,
            "ingests": 2,
            "records": 900,
            "last_ingested": "2025-01-02T08:00:00",
        }
    }

    previous_console = cli.console
    cli.console = None
    try:
        cli._handle_ns_drift(argparse.Namespace(since="3d"), brain)
    finally:
        cli.console = previous_console

    output = capsys.readouterr().out
    assert "Namespace Drift" in output
    assert "3d" in output


def test_handle_report_audit_writes_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class AuditBrain:
        def namespace_activity(self) -> dict[str, dict[str, object]]:
            return {
                "default": {
                    "last_ingested": "2025-01-01T00:00:00",
                    "documents": 10,
                    "documents_delta": 2,
                    "chunks": 40,
                    "chunks_delta": 8,
                    "records": 80,
                    "growth_percent": 25.0,
                    "ingest_runs": 3,
                }
            }

        def namespace_drift(self, _window) -> dict[str, dict[str, object]]:  # type: ignore[override]
            return {
                "default": {
                    "documents_added": 3,
                    "chunks_added": 9,
                    "growth_percent": 30.0,
                    "ingests": 2,
                    "records": 80,
                    "last_ingested": "2025-01-01T00:00:00",
                }
            }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "list_snapshots", lambda limit=None: [{"name": "snapshot_test", "created_at": "2025-01-01T00:00:00", "files": [], "hash": "abc", "path": "data/snapshots/snapshot.tar.gz"}])
    monkeypatch.setattr(cli, "load_lifecycle_history", lambda limit=None: [{"timestamp": "2025-01-02T00:00:00", "action": "snapshot", "detail": {"name": "snapshot_test"}}])

    previous_console = cli.console
    cli.console = None
    try:
        cli._handle_report_audit(argparse.Namespace(json=False, md=False, html=False), AuditBrain())
    finally:
        cli.console = previous_console

    output = capsys.readouterr().out
    assert "audit_report.json" in output
    assert Path("data/logs/audit_report.json").exists()
    assert Path("data/logs/audit_report.md").exists()
    assert Path("data/logs/audit_report.html").exists()

    # ensure html flag prints rendered content without error
    previous_console = cli.console
    cli.console = None
    try:
        cli._handle_report_audit(argparse.Namespace(json=False, md=False, html=True), AuditBrain())
    finally:
        cli.console = previous_console


def test_handle_verify_ledger_prints_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    data_dir = tmp_path / "data/logs"
    data_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = data_dir / "verification_ledger.jsonl"
    entries = [
        {
            "timestamp": "2025-01-01T00:00:00Z",
            "version": "v-test",
            "commit": "abc123",
            "health": 95.0,
            "checksum_file": "data/logs/checksums/artifact_hashes.txt",
            "signature": "data/logs/checksums/artifact_hashes.sig",
        },
        {
            "timestamp": "2025-01-02T00:00:00Z",
            "version": "v-test2",
            "commit": "def456",
            "health": 96.0,
            "checksum_file": "data/logs/checksums/artifact_hashes.txt",
            "signature": "data/logs/checksums/artifact_hashes.sig",
        },
    ]
    ledger_path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cli._handle_verify_ledger(argparse.Namespace(), None)

    output = capsys.readouterr().out
    assert "v-test2" in output
    assert "def456" in output
def test_telemetry_analyze_release(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli,
        "build_telemetry_summary",
        lambda: {
            "version": "v-test",
            "commit": "abc123",
            "health_score": 92.5,
            "latest": {},
            "recurring_errors": [],
            "daily_stats": [],
        },
    )
    monkeypatch.setattr(cli, "load_test_history", lambda: [])
    monkeypatch.setattr(cli, "compute_trend", lambda history, days=2: [])

    cli._handle_telemetry_analyze(argparse.Namespace(json=False, release=True), None)

    output = capsys.readouterr().out
    assert "Release context:" in output
    assert "v-test" in output
    assert "abc123" in output
