from __future__ import annotations

import json
import sys
import asyncio
from pathlib import Path

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
from yo.config import Config, NamespaceConfig
from yo import webui
from yo import release as release_module


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
    monkeypatch.setattr(webui.broadcaster, "start", lambda: asyncio.sleep(0))
    monkeypatch.setattr(webui.broadcaster, "stop", lambda: asyncio.sleep(0))
    monkeypatch.setattr(webui.broadcaster, "trigger", lambda: asyncio.sleep(0))
    
    logs_dir = Path("data/logs")
    (logs_dir / "checksums").mkdir(parents=True, exist_ok=True)
    (logs_dir / "checksums" / "artifact_hashes.txt").write_text("hash", encoding="utf-8")
    (logs_dir / "checksums" / "artifact_hashes.sig").write_text("sig", encoding="utf-8")
    manifest_payload = {
        "version": "v0.5.0",
        "commit": "abc1234",
        "timestamp": "2025-11-07T00:00:00Z",
        "health": 97.2,
        "release_bundle": "releases/release_v0.5.0.tar.gz",
        "bundle_signature": "releases/release_v0.5.0.tar.gz.sig",
        "bundle_checksum": "deadbeef",
        "manifest_path": str(Path("releases") / f"{release_module.RELEASE_MANIFEST_PREFIX}v0.5.0.json"),
    }
    (logs_dir / "integrity_manifest.json").write_text(json.dumps(manifest_payload), encoding="utf-8")
    releases_dir = Path("releases")
    releases_dir.mkdir(parents=True, exist_ok=True)
    (releases_dir / f"{release_module.RELEASE_MANIFEST_PREFIX}v0.5.0.json").write_text(json.dumps(manifest_payload), encoding="utf-8")
    monkeypatch.setattr(webui, "list_release_manifests", lambda: [manifest_payload])
    monkeypatch.setattr(
        webui,
        "load_release_manifest",
        lambda version: dict(manifest_payload) if version == "v0.5.0" else None,
    )
    monkeypatch.setattr(
        webui,
        "verify_integrity_manifest",
        lambda path: {"success": True, "errors": [], "checksum_valid": True, "artifact_signature": {"success": True}, "bundle_signature": {"success": True}},
    )

    class StubChatStore:
        def send(self, **kwargs):
            message = kwargs.get("message", "")
            reply = f"Echo: {message}" if message else "Echo"
            history = [{"user": message, "assistant": reply}]
            return ("session-1", reply, history, {"context": "ctx", "citations": ["doc.md"]})

        def stream(self, **kwargs):
            return self.send(**kwargs)

    monkeypatch.setattr(webui, "chat_store", StubChatStore())
    (logs_dir / "verification_ledger.jsonl").write_text(json.dumps({
        "timestamp": "2025-01-01T00:00:00Z",
        "version": "v-ledger",
        "commit": "abc123",
        "health": 99.0,
        "checksum_file": "data/logs/checksums/artifact_hashes.txt",
        "signature": "data/logs/checksums/artifact_hashes.sig",
    }) + "\n", encoding="utf-8")
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
    assert payload["verification"]["version"] == "v-ledger"
    assert payload["ingestion"]["enabled"] is True
    assert payload["release"]["version"] == "v0.5.0"
    assert payload["releases"][0]["status"] == "verified"


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


def test_release_endpoints(dummy_client: tuple[TestClient, DummyBrain]) -> None:
    client, _ = dummy_client

    manifest = client.get("/api/release/v0.5.0")
    assert manifest.status_code == 200
    assert manifest.json()["manifest"]["version"] == "v0.5.0"

    releases = client.get("/api/releases")
    assert releases.status_code == 200
    assert releases.json()["releases"][0]["version"] == "v0.5.0"

    verify = client.get("/api/release/v0.5.0/verify")
    assert verify.status_code == 200
    payload = verify.json()
    assert payload["version"] == "v0.5.0"
    assert payload["success"] is True


def test_config_endpoints(dummy_client: tuple[TestClient, DummyBrain], monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = dummy_client

    state = {"model": "ollama:llama3"}

    def fake_get_config(*_args, **_kwargs):
        return Config(
            namespace="default",
            model_spec=state["model"],
            embed_model_spec="ollama:nomic-embed-text",
            model_provider="ollama",
            model_name=state["model"].split(":", 1)[-1],
            embed_provider="ollama",
            embed_name="nomic-embed-text",
            db_uri="sqlite:///data/milvus_lite.db",
            data_dir=Path("data"),
            namespace_overrides={},
            sources={},
        )

    updates: dict[str, object] = {}

    def fake_update_config(key: str, value: str, *, namespace: str | None = None, data_dir=None) -> None:
        updates.update({"key": key, "value": value, "namespace": namespace})
        if namespace:
            return
        if key == "model":
            state["model"] = value

    monkeypatch.setattr(webui, "get_config", fake_get_config)
    monkeypatch.setattr(webui, "update_config_value", fake_update_config)

    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["model"] == "ollama:llama3"

    resp2 = client.post("/api/config", json={"key": "model", "value": "ollama:gemma"})
    assert resp2.status_code == 200
    payload = resp2.json()
    assert payload["config"]["model"] == "ollama:gemma"
    assert updates["value"] == "ollama:gemma"


def test_chat_endpoint(dummy_client: tuple[TestClient, DummyBrain]) -> None:
    client, _ = dummy_client

    resp = client.post("/api/chat", json={"namespace": "default", "message": "Hello", "stream": True})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["reply"]["text"].startswith("Echo")
    assert payload["history"][0]["user"] == "Hello"
    assert payload["stream"] is True


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
