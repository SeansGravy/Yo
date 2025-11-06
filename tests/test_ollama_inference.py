from __future__ import annotations

import json

import pytest

import yo.backends as backends


def test_run_ollama_chat_non_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class DummyResponse:
        def __init__(self) -> None:
            captured["called"] = True

        def raise_for_status(self) -> None:
            return

        def json(self) -> dict[str, object]:
            return {"response": "hello world"}

    monkeypatch.setattr(backends.httpx, "post", lambda *args, **kwargs: DummyResponse())

    result = backends.run_ollama_chat("dummy", "ping", stream=False, timeout=1.0)
    assert captured.get("called") is True
    assert result == "hello world"


def test_run_ollama_chat_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads = [
        json.dumps({"response": "hello "}),
        json.dumps({"message": {"content": "world"}}),
        "",
    ]

    class DummyStreamResponse:
        def __init__(self) -> None:
            self._iter = iter(payloads)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def raise_for_status(self) -> None:
            return

        def iter_lines(self):
            return self._iter

    def dummy_stream(*args, **kwargs):
        return DummyStreamResponse()

    monkeypatch.setattr(backends.httpx, "stream", dummy_stream)

    result = backends.run_ollama_chat("dummy", "ping", stream=True, timeout=1.0)
    assert result == "hello world"
