from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest
from starlette.testclient import TestClient

import yo.webui as webui
from yo.chat import ChatSessionStore


class StubBrain:
    def __init__(self) -> None:
        self._chat_history: List[Dict[str, str]] = []

    def chat(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
    ) -> Dict[str, Any]:
        self._chat_history.append({"user": message})
        return {"response": "quick reply", "context": "ctx", "citations": ["doc.md"]}

    def chat_stream(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
    ):
        time.sleep(2)
        yield {"token": "", "done": True, "response": "stream reply", "citations": []}

    async def chat_async(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
        timeout: float | None = None,
    ) -> Dict[str, Any]:
        return {"response": "quick reply", "context": "ctx", "citations": ["doc.md"]}


def test_api_chat_returns_before_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webui, "get_brain", lambda: StubBrain())
    monkeypatch.setenv("YO_CHAT_STREAM_TIMEOUT", "0.3")
    monkeypatch.setenv("YO_CHAT_TIMEOUT", "1.0")
    store = ChatSessionStore()
    monkeypatch.setattr(webui, "chat_store", store)

    async def _noop(*_args, **_kwargs):  # type: ignore[return-value]
        return None

    monkeypatch.setattr(webui.broadcaster, "start", _noop)
    monkeypatch.setattr(webui.broadcaster, "stop", _noop)

    def slow_stream(
        self,
        *,
        brain: Any,
        namespace: str,
        message: str,
        session_id: str | None = None,
        web: bool = False,
    ):
        time.sleep(1.5)
        return ("slow-session", "", [], {"tokens_emitted": 0, "fallback_used": True})

    monkeypatch.setattr(ChatSessionStore, "stream", slow_stream, raising=True)

    with TestClient(webui.app) as client:
        started = time.perf_counter()
        response = client.post(
            "/api/chat",
            json={
                "namespace": "default",
                "message": "ping",
                "session_id": "timeout-test",
                "stream": True,
            },
        )
        elapsed = time.perf_counter() - started

    assert response.status_code == 200
    payload = response.json()
    assert payload["fallback"] is True
    assert elapsed < 2.5, f"/api/chat took too long: {elapsed:.2f}s"
