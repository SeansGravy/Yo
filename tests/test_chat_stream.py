from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable

import pytest

from starlette.testclient import TestClient

from yo.chat import ChatSessionStore
from yo.events import get_event_bus
import yo.webui as webui


class StubBrain:
    """Brain stub that yields a predictable streaming sequence."""

    def __init__(self, tokens: Iterable[str], reply: str) -> None:
        self._tokens = list(tokens)
        self._reply = reply

    def chat_stream(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: list[Dict[str, str]] | None = None,
        web: bool = False,
    ) -> Iterable[Dict[str, Any]]:
        for token in self._tokens:
            yield {"token": token, "done": False}
        yield {"token": "", "done": True, "response": self._reply, "citations": []}

    def chat(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: list[Dict[str, str]] | None = None,
        web: bool = False,
    ) -> Dict[str, Any]:
        return {"response": self._reply, "citations": []}


@pytest.mark.asyncio
async def test_chat_stream_emits_events(monkeypatch: pytest.MonkeyPatch) -> None:
    store = ChatSessionStore()
    bus = get_event_bus()
    queue = await bus.subscribe()
    try:
        while not queue.empty():
            queue.get_nowait()

        async def run_stream() -> tuple[str, str, list[dict[str, str]], dict[str, Any]]:
            return await asyncio.to_thread(
                store.stream,
                brain=StubBrain(tokens=["Hello ", "world"], reply="Hello world"),
                namespace="default",
                message="ping",
                session_id=None,
                web=False,
            )

        session_id, reply, history, metadata = await run_stream()
        assert reply == "Hello world"
        assert history[-1]["assistant"] == "Hello world"

        await asyncio.sleep(0.05)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        types = [event.get("type") for event in events if event.get("session_id") == session_id]
        assert "chat_started" in types
        assert "chat_token" in types
        assert "chat_complete" in types
        assert "chat_message" in types
        complete_event = next(event for event in events if event.get("type") == "chat_complete")
        assert complete_event["history"][-1]["assistant"] == "Hello world"
    finally:
        await bus.unsubscribe(queue)


@pytest.mark.asyncio
async def test_chat_send_emits_message_event() -> None:
    store = ChatSessionStore()
    bus = get_event_bus()
    queue = await bus.subscribe()
    try:
        while not queue.empty():
            queue.get_nowait()

        def run_send() -> tuple[str, str, list[dict[str, str]], dict[str, Any]]:
            return store.send(
                brain=StubBrain(tokens=[], reply="Acknowledged."),
                namespace="default",
                message="ping",
                session_id=None,
                web=False,
            )

        session_id, reply, history, metadata = await asyncio.to_thread(run_send)
        assert reply == "Acknowledged."
        assert history[-1]["assistant"] == "Acknowledged."

        await asyncio.sleep(0.05)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        message_events = [
            event for event in events if event.get("type") == "chat_message" and event.get("session_id") == session_id
        ]
        assert message_events, "Expected chat_message event to be published."
        assert message_events[0]["reply"]["text"] == "Acknowledged."
    finally:
        await bus.unsubscribe(queue)


def test_chat_rest_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class RestStub:
        def chat(self, **kwargs):
            return {"response": "Fallback reply", "citations": []}

        def chat_stream(self, **kwargs):
            yield {"token": "Fallback", "done": True, "response": "Fallback reply", "citations": []}

    monkeypatch.setattr(webui, "get_brain", lambda: RestStub())
    monkeypatch.setenv("YO_CHAT_STREAM_FALLBACK", "force")
    monkeypatch.setattr(webui, "chat_store", ChatSessionStore())

    async def _noop(*_args, **_kwargs):  # type: ignore[return-value]
        return None

    monkeypatch.setattr(webui.broadcaster, "start", _noop)
    monkeypatch.setattr(webui.broadcaster, "stop", _noop)

    with TestClient(webui.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "namespace": "default",
                "message": "ping",
                "session_id": "rest-fallback",
                "stream": True,
            },
        )
    payload = response.json()
    assert payload["stream"] is False
    assert payload["reply"]["text"] == "Fallback reply"
    assert payload["fallback"] is True
