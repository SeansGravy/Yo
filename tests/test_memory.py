from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_yomemory_connects(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[str, str]] = []

    def fake_connect(*, alias: str, uri: str) -> None:
        calls.append((alias, uri))

    from yo import memory  # import inside to allow patching below

    monkeypatch.setattr(memory.connections, "connect", fake_connect)

    custom_uri = "sqlite:///unit-test.db"
    memory.YoMemory(uri=custom_uri)

    captured = capsys.readouterr()
    assert calls == [("default", custom_uri)]
    assert custom_uri in captured.out
