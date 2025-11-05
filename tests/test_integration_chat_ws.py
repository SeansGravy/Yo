from __future__ import annotations

from starlette.testclient import TestClient

import yo.webui as webui
from yo.chat import ChatSessionStore


class StubBrain:
    def chat_stream(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: list[dict[str, str]] | None = None,
        web: bool = False,
    ):
        yield {"token": "Hello ", "done": False}
        yield {"token": "world", "done": False}
        yield {"token": "", "done": True, "response": "Hello world", "citations": []}

    def chat(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: list[dict[str, str]] | None = None,
        web: bool = False,
    ) -> dict[str, object]:
        return {"response": "Hello world", "citations": []}


def test_chat_ws_stream(monkeypatch):
    monkeypatch.setattr(webui, "get_brain", lambda: StubBrain())
    monkeypatch.setenv("YO_CHAT_STREAM_FALLBACK", "auto")
    monkeypatch.setattr(webui, "chat_store", ChatSessionStore())

    async def _noop(*_args, **_kwargs):  # type: ignore[return-value]
        return None

    monkeypatch.setattr(webui.broadcaster, "start", _noop)
    monkeypatch.setattr(webui.broadcaster, "stop", _noop)
    webui.configure_runtime("127.0.0.1", 0, debug=False)

    with TestClient(webui.app) as client:
        with client.websocket_connect("/ws/chat/integration") as websocket:
            response = client.post(
                "/api/chat",
                json={
                    "namespace": "default",
                    "message": "ping",
                    "session_id": "integration",
                    "stream": True,
                },
            )
            payload = response.json()
            assert payload["stream"] is True

            messages = []
            for _ in range(5):
                event = websocket.receive_json()
                messages.append(event)
                if event.get("type") == "chat_complete":
                    break

    assert any(event.get("type") == "chat_complete" for event in messages)
    assert any("Hello world" in str(event.get("reply", "")) for event in messages)
