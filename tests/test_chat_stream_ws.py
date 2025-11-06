from __future__ import annotations

import asyncio

from starlette.testclient import TestClient

import yo.webui as webui
from yo.events import get_event_bus


def test_ws_receives_message_after_publish() -> None:
    client = TestClient(webui.app)
    bus = get_event_bus()

    with client.websocket_connect("/ws/chat/unit-session") as websocket:
        asyncio.run(
            bus.publish(
                "chat_message",
                {
                    "session_id": "unit-session",
                    "namespace": "default",
                    "reply": {"text": "unit test reply"},
                    "history": [],
                    "fallback": False,
                },
            )
        )
        data = websocket.receive_json()
        assert data.get("type") == "chat_message"
        reply = data.get("reply") or {}
        assert isinstance(reply, dict)
        assert reply.get("text") == "unit test reply"
