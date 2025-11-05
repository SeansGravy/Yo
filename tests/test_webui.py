from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

try:  # pragma: no cover - optional dependency for unit tests
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - skip when FastAPI is unavailable
    pytest.skip("fastapi not installed", allow_module_level=True)

from yo.backends import BackendStatus, BackendSummary
from yo.brain import MissingDependencyError
from yo import webui


class FakeUpload:
    def __init__(self, filename: str, payload: bytes) -> None:
        self.filename = filename
        self._payload = payload

    async def read(self) -> bytes:
        return self._payload

    async def close(self) -> None:  # pragma: no cover - compatibility shim
        return None


class DummyBrain:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        now = "2024-11-02T10:00:00"
        self._activity = {
            "default": {
                "last_ingested": now,
                "documents": 3,
                "documents_delta": 1,
                "chunks": 42,
                "chunks_delta": 5,
                "records": 84,
                "growth_percent": 12.5,
                "ingest_runs": 2,
            },
            "projects": {
                "last_ingested": None,
                "documents": None,
                "documents_delta": None,
                "chunks": None,
                "chunks_delta": None,
                "records": 0,
                "growth_percent": 0.0,
                "ingest_runs": 0,
            },
        }
        self._drift = {
            "default": {
                "documents_added": 2,
                "chunks_added": 8,
                "growth_percent": 18.0,
                "ingests": 2,
                "records": 84,
                "last_ingested": now,
            },
            "projects": {
                "documents_added": 0,
                "chunks_added": 0,
                "growth_percent": 0.0,
                "ingests": 0,
                "records": 0,
                "last_ingested": None,
            },
        }

    def ns_list(self, *, silent: bool = False) -> list[str]:  # noqa: D401 - simple stub
        return ["default", "projects"]

    def namespace_activity(self) -> dict[str, dict[str, object]]:
        return self._activity

    def namespace_drift(self, _window) -> dict[str, dict[str, object]]:  # type: ignore[override]
        return self._drift

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
    assert "health" in payload
    assert payload["drift_window"] == "7d"
    assert payload["ingestion"]["enabled"] is True


def test_ingest_endpoint_uses_brain(
    dummy_client: tuple[TestClient, DummyBrain],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, brain = dummy_client

    async def fake_extract(request):
        return "ideas", [FakeUpload("note.txt", b"hello")]

    monkeypatch.setattr(webui, "_extract_uploads", fake_extract)

    response = client.post("/api/ingest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingest"]["namespace"] == "ideas"
    assert brain.calls and brain.calls[0][1] == "ideas"


def test_ingest_endpoint_returns_dependency_error(
    dummy_client: tuple[TestClient, DummyBrain],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, brain = dummy_client

    async def fake_extract(request):
        return "default", [FakeUpload("report.pdf", b"pdf-bytes")]

    monkeypatch.setattr(webui, "_extract_uploads", fake_extract)

    def failing_ingest(path: str, namespace: str = "default") -> None:
        raise MissingDependencyError("Install openpyxl")

    monkeypatch.setattr(brain, "ingest", failing_ingest)

    response = client.post("/api/ingest")

    assert response.status_code == 400
    payload = response.json()
    assert "openpyxl" in (payload.get("detail") or "")


def test_ui_route_serves_dashboard(dummy_client: tuple[TestClient, DummyBrain]) -> None:
    client, _ = dummy_client

    response = client.get("/ui")
    assert response.status_code == 200
    assert "Yo Lite UI" in response.text


def test_status_endpoint_disables_ingestion_when_backends_missing(
    dummy_client: tuple[TestClient, DummyBrain],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = dummy_client

    degraded = BackendSummary(
        milvus=BackendStatus(False, "Install Milvus Lite support via `pip install pymilvus[milvus_lite]`.", None),
        ollama_python=BackendStatus(True, "Bindings ready", "0.1.0"),
        ollama_cli=BackendStatus(False, "Install the Ollama CLI.", None),
    )
    monkeypatch.setattr(webui, "detect_backends", lambda: degraded)

    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingestion"]["enabled"] is False
    reason = payload["ingestion"]["reason"] or ""
    assert "Milvus Lite" in reason and "Ollama" in reason
