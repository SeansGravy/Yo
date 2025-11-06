from __future__ import annotations

from starlette.testclient import TestClient

import yo.webui as webui


def test_chat_health_endpoint_returns_ok(monkeypatch) -> None:
    monkeypatch.setattr(webui, "SERVER_READY", True)
    client = TestClient(webui.app)

    response = client.get("/api/health/chat")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.5.9.1"
    assert "stream_rate" in payload
    assert "avg_latency" in payload
    assert "avg_stream_latency_ms" in payload
    assert "stream_drop_rate" in payload
    assert "ollama_healthy" in payload
    assert "restart_count" in payload
