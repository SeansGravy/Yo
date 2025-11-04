from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient

from yo.backends import BackendStatus, BackendSummary
from yo import webui


class DummyBrain:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def ns_list(self, *, silent: bool = False) -> list[str]:  # noqa: D401 - simple stub
        return ["default", "projects"]

    def namespace_activity(self) -> dict[str, dict[str, object]]:
        return {
            "default": {
                "last_ingested": "2024-11-02T10:00:00",
                "documents": 3,
                "chunks": 42,
                "records": 84,
            },
            "projects": {
                "last_ingested": None,
                "documents": None,
                "chunks": None,
                "records": 0,
            },
        }

    def ingest(self, path: str, namespace: str = "default") -> dict[str, object]:
        assert Path(path).exists()
        self.calls.append((path, namespace))
        return {
            "namespace": namespace,
            "documents_ingested": 1,
            "chunks_ingested": 2,
        }


@pytest.fixture
def healthy_backends() -> BackendSummary:
    return BackendSummary(
        milvus=BackendStatus(True, "Milvus ready", "2.4.4"),
        ollama_python=BackendStatus(True, "Ollama bindings ready", "0.1.0"),
        ollama_cli=BackendStatus(True, "Ollama CLI ready", "ollama 0.1.32"),
    )


@pytest.fixture
def dummy_client(monkeypatch: pytest.MonkeyPatch, healthy_backends: BackendSummary) -> tuple[TestClient, DummyBrain]:
    dummy = DummyBrain()
    if hasattr(webui.get_brain, "cache_clear"):
        webui.get_brain.cache_clear()

    monkeypatch.setattr(webui, "detect_backends", lambda: healthy_backends)
    monkeypatch.setattr(webui, "get_brain", lambda: dummy)
    monkeypatch.setattr(webui, "MULTIPART_AVAILABLE", True)
    client = TestClient(webui.app)
    return client, dummy


def test_status_endpoint_reports_namespaces(dummy_client: tuple[TestClient, DummyBrain]) -> None:
    client, _ = dummy_client

    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["backends"]["milvus"]["available"] is True
    assert payload["backends"]["ollama"]["ready"] is True
    assert len(payload["namespaces"]) == 2
    assert payload["namespaces"][0]["name"] == "default"
    assert payload["ingestion"]["enabled"] is True


def test_ingest_endpoint_uses_brain(
    dummy_client: tuple[TestClient, DummyBrain],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, brain = dummy_client

    class FakeUpload:
        def __init__(self, filename: str, payload: bytes) -> None:
            self.filename = filename
            self._payload = payload

        async def read(self) -> bytes:
            return self._payload

        async def close(self) -> None:  # pragma: no cover - compatibility shim
            return None

    async def fake_extract(request):
        return "ideas", [FakeUpload("note.txt", b"hello")]

    monkeypatch.setattr(webui, "_extract_uploads", fake_extract)

    response = client.post("/api/ingest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingest"]["namespace"] == "ideas"
    assert brain.calls and brain.calls[0][1] == "ideas"


def test_ui_route_serves_dashboard(dummy_client: tuple[TestClient, DummyBrain]) -> None:
    client, _ = dummy_client

    response = client.get("/ui")
    assert response.status_code == 200
    assert "Yo Lite UI" in response.text
