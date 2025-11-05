from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest
from starlette.testclient import TestClient

import yo.webui as webui
from yo.chat import ChatSessionStore


class StreamingBrain:
    def __init__(self, tokens: List[str], final: str) -> None:
        self._tokens = tokens
        self._final = final

    def chat_stream(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
    ):
        for token in self._tokens:
            yield {"type": "chat_token", "token": token, "done": False}
        yield {"done": True, "response": self._final, "citations": []}

    def chat(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
    ) -> Dict[str, Any]:
        return {"response": self._final, "citations": []}

    async def chat_async(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
        timeout: float | None = None,
    ) -> Dict[str, Any]:
        return {"text": self._final, "response": self._final}


class FallbackBrain:
    def chat(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
    ) -> Dict[str, Any]:
        return {"response": "fallback reply", "citations": []}

    def chat_stream(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
    ):
        yield from ()

    async def chat_async(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
        timeout: float | None = None,
    ) -> Dict[str, Any]:
        return {"text": "async fallback", "response": "async fallback"}


class ExplodingBrain:
    def chat(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
    ) -> Dict[str, Any]:
        return {"response": "", "citations": []}

    def chat_stream(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
    ):
        yield from ()

    async def chat_async(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
        timeout: float | None = None,
    ) -> Dict[str, Any]:
        raise RuntimeError("model failure")


@pytest.fixture(autouse=True)
def _reset_chat_store(monkeypatch: pytest.MonkeyPatch) -> None:
    store = ChatSessionStore()
    monkeypatch.setattr(webui, "chat_store", store)

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(webui.broadcaster, "start", _noop)
    monkeypatch.setattr(webui.broadcaster, "stop", _noop)


def test_delivery_streaming_path(monkeypatch: pytest.MonkeyPatch) -> None:
    brain = StreamingBrain(tokens=["Hello ", "world"], final="Hello world")
    monkeypatch.setattr(webui, "get_brain", lambda: brain)
    monkeypatch.delenv("YO_CHAT_STREAM_FALLBACK", raising=False)

    with TestClient(webui.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "namespace": "default",
                "message": "hi",
                "session_id": "stream-session",
                "stream": True,
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["type"] == "chat_message"
    assert payload["stream"] is True
    assert payload["fallback"] is False
    assert payload["reply"]["text"].strip() != ""
    assert payload["history"][-1]["assistant"].strip() != ""


def test_delivery_forced_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    brain = FallbackBrain()
    monkeypatch.setattr(webui, "get_brain", lambda: brain)
    monkeypatch.setenv("YO_CHAT_STREAM_FALLBACK", "force")

    with TestClient(webui.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "namespace": "default",
                "message": "force fallback",
                "session_id": "fallback-session",
                "stream": True,
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["type"] == "chat_message"
    assert payload["stream"] is False
    assert payload["fallback"] is True
    assert payload["reply"]["text"].strip() != ""
    assert payload["history"][-1]["assistant"].strip() != ""


def test_delivery_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webui, "get_brain", lambda: ExplodingBrain())
    monkeypatch.delenv("YO_CHAT_STREAM_FALLBACK", raising=False)

    def _timeout_stream(
        self,
        *,
        brain: Any,
        namespace: str,
        message: str,
        session_id: str | None = None,
        web: bool = False,
    ):
        raise asyncio.TimeoutError

    def _timeout_send(
        self,
        *,
        brain: Any,
        namespace: str,
        message: str,
        session_id: str | None = None,
        web: bool = False,
        fallback: bool = False,
    ):
        raise asyncio.TimeoutError

    monkeypatch.setattr(ChatSessionStore, "stream", _timeout_stream, raising=True)
    monkeypatch.setattr(ChatSessionStore, "send", _timeout_send, raising=True)

    with TestClient(webui.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "namespace": "default",
                "message": "trigger failure",
                "session_id": "failure-session",
                "stream": True,
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["type"] == "chat_message"
    assert payload["stream"] is False
    assert payload["fallback"] is True
    assert payload["reply"]["text"].strip() != ""
    assert payload["history"][-1]["assistant"].strip() != ""
