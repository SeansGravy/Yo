from __future__ import annotations

import json
from pathlib import Path

import pytest

from yo import monitor_ollama


def test_monitor_triggers_restart_and_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "ollama_monitor.log"
    monkeypatch.setattr(monitor_ollama, "LOG_PATH", log_path)

    results = [
        (False, 1100.0, "timeout"),
        (False, 1200.0, "timeout"),
        (True, 900.0, None),
    ]

    def fake_ping(timeout: float = monitor_ollama.DEFAULT_TIMEOUT):
        if not results:
            return True, 800.0, None
        return results.pop(0)

    subprocess_calls: list[list[str]] = []

    def fake_subprocess_run(cmd, check=False, timeout=15):
        subprocess_calls.append(cmd)

    monkeypatch.setattr(monitor_ollama, "ping_ollama", fake_ping)
    monkeypatch.setattr(monitor_ollama.subprocess, "run", fake_subprocess_run)

    monitor_ollama.run_monitor(
        interval=0.0,
        timeout=0.1,
        watch=False,
        max_cycles=3,
        sleep_fn=lambda _: None,
    )

    assert subprocess_calls, "Expected restart command to be issued."
    entries = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))

    events = {entry.get("event") for entry in entries}
    assert "ollama_restart" in events
    assert "ping_success" in events or "ollama_back_online" in events
