from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_run_tasks_moves_and_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yo import task_runner

    tasks_root = tmp_path / "tasks"
    active = tasks_root / "active"
    completed = tasks_root / "completed"
    failed = tasks_root / "failed"
    active.mkdir(parents=True)
    completed.mkdir(parents=True)
    failed.mkdir(parents=True)

    card = active / "test.md"
    card.write_text("# test card", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(task_runner, "_print_success_echo", lambda version, path: None)

    task_runner.run_tasks()

    assert not card.exists()
    completed_card = completed / "test.md"
    assert completed_card.exists()
    content = completed_card.read_text(encoding="utf-8")
    assert "Codex Execution Log" in content
