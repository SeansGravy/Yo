from __future__ import annotations

import argparse
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

    def ingest(self, path: str, namespace: str = "default") -> None:
        self.calls.append((path, namespace))

    def ns_switch(self, namespace: str) -> None:
        self.switch_calls.append(namespace)

    def ns_purge(self, namespace: str) -> None:
        self.purge_calls.append(namespace)


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
