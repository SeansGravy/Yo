from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest
from starlette.testclient import TestClient

import yo.webui as webui
from yo.chat import ChatSessionStore


class AsyncFallbackBrain:
    def chat(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: List[Dict[str, str]] | None = None,
        web: bool = False,
    ) -> Dict[str, Any]:
        return {"response": "unused sync reply"}

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
        return {"response": "async fallback text", "context": "ctx", "citations": ["doc.md"]}


def _timeout_stream(
    self,
    *,
    brain: Any,
    namespace: str,
    message: str,
    session_id: str | None = None,
    web: bool = False,
) -> Any:
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
) -> Any:
    raise asyncio.TimeoutError


def test_chat_fallback_always_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webui, "get_brain", lambda: AsyncFallbackBrain())
    store = ChatSessionStore()
    monkeypatch.setattr(webui, "chat_store", store)
    monkeypatch.setenv("YO_CHAT_STREAM_TIMEOUT", "0.05")
    monkeypatch.setenv("YO_CHAT_TIMEOUT", "0.1")

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(webui.broadcaster, "start", _noop)
    monkeypatch.setattr(webui.broadcaster, "stop", _noop)
    monkeypatch.setattr(ChatSessionStore, "stream", _timeout_stream, raising=True)
    monkeypatch.setattr(ChatSessionStore, "send", _timeout_send, raising=True)

    with TestClient(webui.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "namespace": "default",
                "message": "ping",
                "session_id": "fallback-verification",
                "stream": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    reply_payload = payload.get("reply") or {}
    assert isinstance(reply_payload, dict)
    reply_text = (reply_payload.get("text") or "").strip()
    assert reply_text == "async fallback text"
    assert payload.get("fallback") is True
    assert payload.get("stream") is False
    assert payload.get("type") == "chat_message"
    assert reply_text != ""
    assert payload.get("history"), "Expected history to be returned for fallback reply."


def test_fallback_returns_text_when_model_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    class BlankBrain:
        def chat(
            self,
            *,
            message: str,
            namespace: str | None = None,
            history: List[Dict[str, str]] | None = None,
            web: bool = False,
        ) -> Dict[str, Any]:
            return {"response": ""}

        async def chat_async(
            self,
            *,
            message: str,
            namespace: str | None = None,
            history: List[Dict[str, str]] | None = None,
            web: bool = False,
            timeout: float | None = None,
        ) -> Dict[str, Any]:
            return {"text": ""}

        def chat_stream(self, **_: Any) -> List[Dict[str, Any]]:
            return []

    monkeypatch.setattr(webui, "get_brain", lambda: BlankBrain())
    monkeypatch.setattr(webui, "chat_store", ChatSessionStore())
    monkeypatch.setenv("YO_CHAT_STREAM_FALLBACK", "force")

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(webui.broadcaster, "start", _noop)
    monkeypatch.setattr(webui.broadcaster, "stop", _noop)

    with TestClient(webui.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "namespace": "default",
                "message": "ping",
                "session_id": "blank-fallback",
                "stream": False,
            },
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload.get("fallback") is True
    assert payload.get("stream") is False
    reply_payload = payload.get("reply") or {}
    reply_text = (reply_payload.get("text") or "").strip()
    assert reply_text != ""
