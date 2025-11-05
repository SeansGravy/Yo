from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

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
    monkeypatch.setattr(
        cli,
        "_verify_signature_artifacts",
        lambda: {
            "success": True,
            "signer": "Codex CI",
            "message": "",
            "checksum": "data/logs/checksums/artifact_hashes.txt",
            "signature": "data/logs/checksums/artifact_hashes.sig",
            "timestamp": "2025-01-01T00:00:00Z",
        },
    )
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


def test_handle_verify_signature_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli,
        "_verify_signature_artifacts",
        lambda: {
            "success": True,
            "signer": "Codex CI",
            "message": "",
            "checksum": "data/logs/checksums/artifact_hashes.txt",
            "signature": "data/logs/checksums/artifact_hashes.sig",
        },
    )

    cli._handle_verify_signature(argparse.Namespace(json=True), None)

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["success"] is True
    assert payload["signer"] == "Codex CI"


def test_handle_verify_clone_matches_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    checksums_dir = tmp_path / "data/logs/checksums"
    checksums_dir.mkdir(parents=True, exist_ok=True)
    checksum_path = checksums_dir / "artifact_hashes.txt"
    checksum_path.write_text("abc123\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "_verify_signature_artifacts",
        lambda: {
            "success": True,
            "signer": "Codex CI",
            "message": "",
            "checksum": str(checksum_path),
            "signature": "data/logs/checksums/artifact_hashes.sig",
        },
    )
    monkeypatch.setattr(cli.shutil, "which", lambda cmd: "/usr/bin/git" if cmd == "git" else None)

    def fake_run(args, capture_output=True, text=True, env=None):
        if list(args[:4]) == ["git", "fetch", "origin", "main"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if list(args[:4]) == ["git", "show", "origin/main:data/logs/checksums/artifact_hashes.txt"]:
            return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli._handle_verify_clone(argparse.Namespace(json=False), None)

    output = capsys.readouterr().out
    assert "Signature valid" in output
    assert "matches origin" in output


def test_handle_package_release_prints_paths(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_build_release_bundle(**kwargs: object) -> dict[str, object]:
        captured_kwargs.update(kwargs)
        return {
            "bundle": "releases/release_v0.5.0.tar.gz",
            "signature": "releases/release_v0.5.0.tar.gz.sig",
            "manifest": "data/logs/integrity_manifest.json",
            "manifest_version": "releases/integrity_manifest_v0.5.0.json",
            "manifest_data": {
                "version": "v0.5.0",
                "commit": "abc1234",
                "health": 95.2,
            },
        }

    monkeypatch.setattr(cli, "build_release_bundle", fake_build_release_bundle)

    cli._handle_package_release(
        argparse.Namespace(version=None, signer=None, output=None, manifest=None, json=False),
        None,
    )

    output = capsys.readouterr().out
    assert "release_v0.5.0.tar.gz" in output
    assert captured_kwargs.get("version") is None


def test_handle_verify_manifest_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli,
        "verify_integrity_manifest",
        lambda path: {"success": True, "manifest": {"version": "v0.5.0"}},
    )

    cli._handle_verify_manifest(argparse.Namespace(path=None, json=True), None)

    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["manifest"]["version"] == "v0.5.0"


def test_handle_release_list_prints(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli,
        "list_release_manifests",
        lambda: [
            {
                "version": "v0.5.0",
                "timestamp": "2025-11-07T04:00:00Z",
                "health": 95.2,
                "release_bundle": "releases/release_v0.5.0.tar.gz",
            }
        ],
    )

    cli._handle_release_list(argparse.Namespace(json=False), None)
    output = capsys.readouterr().out
    assert "v0.5.0" in output
    assert "release_v0.5.0.tar.gz" in output


def test_handle_release_info_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli,
        "load_release_manifest",
        lambda version: {"version": version, "commit": "abc123", "manifest_path": "releases/integrity.json"},
    )

    cli._handle_release_info(argparse.Namespace(version="v0.5.0", json=True), None)
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == "v0.5.0"
    assert payload["manifest_path"] == "releases/integrity.json"


def test_handle_system_clean_release(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    captured: dict[str, object] = {}

    def fake_clean(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(cli, "system_clean", fake_clean)

    cli._handle_system_clean(argparse.Namespace(dry_run=False, older_than=14, release=True), None)
    assert captured.get("release") is True


def test_handle_config_edit_uses_editor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    calls: list[list[str]] = []

    monkeypatch.setenv("EDITOR", "test-editor")
    monkeypatch.setattr(cli, "ENV_FILE", env_path, raising=False)
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, check=False: calls.append(cmd))

    cli._handle_config_edit(argparse.Namespace(), None)

    assert env_path.exists()
    assert calls == [["test-editor", str(env_path)]]


def test_handle_logs_tail_outputs_formatted_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    events_dir = tmp_path / "data/logs/sessions/events"
    events_dir.mkdir(parents=True, exist_ok=True)
    log_path = events_dir / "events_20250101.jsonl"
    entry = {
        "type": "chat_message",
        "timestamp": "2025-01-01T12:00:00Z",
        "session_id": "abc",
        "namespace": "default",
    }
    log_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    cli._handle_logs_tail(argparse.Namespace(log_type="events", lines=5, json=False), None)

    output = capsys.readouterr().out
    assert "Tail of events log" in output
    assert "chat_message" in output


def test_handle_logs_tail_json_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    chat_dir = tmp_path / "data/logs/sessions/chat"
    chat_dir.mkdir(parents=True, exist_ok=True)
    log_path = chat_dir / "chat_20250102.jsonl"
    log_path.write_text(
        json.dumps({"event": "message", "session_id": "s1", "namespace": "default", "user": "hi"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    cli._handle_logs_tail(argparse.Namespace(log_type="chat", lines=1, json=True), None)

    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "chat"
    assert payload["lines"]
    assert payload["log_path"].endswith("chat_20250102.jsonl")


def test_health_monitor_success_creates_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    now = datetime.now(timezone.utc)
    summary = {
        "timestamp": now.isoformat(),
        "status": "✅ Verify successful",
        "tests_total": 10,
        "tests_passed": 10,
        "pass_rate": 1.0,
    }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_test_summary", lambda: summary)
    monkeypatch.setattr(cli, "load_telemetry_summary", lambda: {"health_score": 97.2})
    monkeypatch.setattr(cli, "build_telemetry_summary", lambda: {"health_score": 97.2})

    cli._handle_health_report(argparse.Namespace(action="monitor", json=False), None)

    output = capsys.readouterr().out
    assert "Health monitor status: OK" in output
    monitor_path = Path("data/logs/health_monitor.jsonl")
    assert monitor_path.exists()
    lines = [line for line in monitor_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = json.loads(lines[-1])
    assert payload["status"] == "ok"
    assert payload["pass_rate"] == 100.0


def test_health_monitor_detects_stale_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=36)
    summary = {
        "timestamp": past.isoformat(),
        "status": "✅ Verify successful",
        "tests_total": 10,
        "tests_passed": 10,
        "pass_rate": 1.0,
    }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_test_summary", lambda: summary)
    monkeypatch.setattr(cli, "load_telemetry_summary", lambda: {"health_score": 92.0})
    monkeypatch.setattr(cli, "build_telemetry_summary", lambda: {"health_score": 92.0})

    with pytest.raises(SystemExit) as excinfo:
        cli._handle_health_report(argparse.Namespace(action="monitor", json=False), None)

    assert excinfo.value.code == 1
    _ = capsys.readouterr()
    monitor_path = Path("data/logs/health_monitor.jsonl")
    assert monitor_path.exists()
    payload = json.loads(monitor_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["status"] == "fail"
    assert any("24" in reason for reason in payload.get("reasons", []))


def test_handle_chat_single_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class DummyBrain:
        active_namespace = "default"

        def __init__(self) -> None:
            self.calls: list[dict] = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            return {"response": "Hello there!", "citations": ["doc.md"]}

    brain = DummyBrain()
    cli._handle_chat(argparse.Namespace(message=["Hi"], ns=None, web=False), brain)

    output = capsys.readouterr().out
    assert "Hello there" in output
    assert brain.calls[0]["web"] is False
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
