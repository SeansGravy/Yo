from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yo.brain as brain_module
from yo.brain import YoBrain
from yo.logging_utils import get_logger


def _build_brain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, namespaces: list[str]) -> tuple[YoBrain, list[str], list[str]]:
    collections = [f"yo_{name}" for name in namespaces]
    drop_calls: list[str] = []

    def list_collections() -> list[str]:
        return list(collections)

    def drop_collection(name: str) -> None:
        drop_calls.append(name)
        if name in collections:
            collections.remove(name)

    monkeypatch.setattr(
        brain_module,
        "utility",
        SimpleNamespace(list_collections=list_collections, drop_collection=drop_collection),
    )

    def fake_get_config(*, cli_args=None, namespace=None):
        ns = (cli_args or {}).get("namespace") or namespace or "default"
        return SimpleNamespace(
            namespace=ns,
            model_spec="ollama:llama3",
            embed_model_spec="ollama:nomic-embed-text",
            model_provider="ollama",
            model_name="llama3",
            embed_provider="ollama",
            embed_name="nomic-embed-text",
            db_uri=str(tmp_path / "milvus_lite.db"),
            data_dir=tmp_path,
            namespace_overrides={},
            sources={
                "model": "default",
                "embed_model": "default",
                "namespace": "default",
                "db_uri": "default",
            },
        )

    def fake_select_model(task_type: str, **_: object) -> SimpleNamespace:
        model = "llama3" if task_type == "chat" else "nomic-embed-text"
        spec = f"ollama:{model}"
        return SimpleNamespace(
            task_type=task_type,
            provider="ollama",
            model=model,
            spec=spec,
            namespace="default",
            source="test",
            fallback=False,
            reason=None,
        )

    monkeypatch.setattr(brain_module, "get_config", fake_get_config)
    monkeypatch.setattr(brain_module, "select_model", fake_select_model)
    monkeypatch.setenv("YO_DATA_DIR", str(tmp_path))

    brain = object.__new__(YoBrain)  # type: ignore[call-arg, return-value]
    brain._logger = get_logger("yo.tests")  # type: ignore[attr-defined]
    brain.data_dir = tmp_path  # type: ignore[attr-defined]
    brain.meta_path = tmp_path / "namespace_meta.json"  # type: ignore[attr-defined]
    brain.state_path = tmp_path / "namespace_state.json"  # type: ignore[attr-defined]
    brain.cache_path = tmp_path / "web_cache.json"  # type: ignore[attr-defined]
    brain.recover_dir = tmp_path / "recoveries"  # type: ignore[attr-defined]
    brain.recover_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[attr-defined]
    brain.active_namespace = "default"  # type: ignore[attr-defined]

    def fake_initialise(self: YoBrain) -> None:  # type: ignore[override]
        self.model_selection = fake_select_model("chat")  # type: ignore[attr-defined]
        self.embedding_selection = fake_select_model("embedding")  # type: ignore[attr-defined]
        self.model_provider = "ollama"  # type: ignore[attr-defined]
        self.embed_provider = "ollama"  # type: ignore[attr-defined]
        self.model_name = "llama3"  # type: ignore[attr-defined]
        self.embed_model = "nomic-embed-text"  # type: ignore[attr-defined]
        self.client = SimpleNamespace()  # type: ignore[attr-defined]
        self.embeddings = SimpleNamespace()  # type: ignore[attr-defined]

    brain._initialise_models = fake_initialise.__get__(brain, YoBrain)  # type: ignore[attr-defined]
    brain.config = fake_get_config(namespace="default")  # type: ignore[attr-defined]
    return brain, collections, drop_calls


def test_ns_switch_updates_state_and_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    brain, collections, _ = _build_brain(tmp_path, monkeypatch, ["default", "research"])
    assert "yo_research" in collections

    brain.ns_switch("research")

    assert brain.active_namespace == "research"  # type: ignore[attr-defined]
    assert brain.cache_path.name == "web_cache_research.json"  # type: ignore[attr-defined]

    state_data = json.loads(brain.state_path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
    assert state_data["active"] == "research"


def test_ns_purge_drops_collection_and_resets_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    brain, collections, drop_calls = _build_brain(tmp_path, monkeypatch, ["default", "reports", "research"])
    brain.active_namespace = "reports"  # type: ignore[attr-defined]

    # Seed namespace metadata that should be pruned.
    meta_payload = {"default": {"documents": 1}, "reports": {"documents": 2}}
    brain.meta_path.write_text(json.dumps(meta_payload), encoding="utf-8")  # type: ignore[attr-defined]

    brain.ns_purge("reports")

    assert drop_calls == ["yo_reports"]
    meta_after = json.loads(brain.meta_path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
    assert "reports" not in meta_after
    assert brain.active_namespace in {"default", "research"}  # type: ignore[attr-defined]

    state_data = json.loads(brain.state_path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
    assert state_data["active"] == brain.active_namespace  # type: ignore[attr-defined]


def test_ns_purge_falls_back_to_first_available_when_default_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    brain, collections, drop_calls = _build_brain(tmp_path, monkeypatch, ["reports", "finance"])
    brain.active_namespace = "reports"  # type: ignore[attr-defined]

    brain.ns_purge("reports")

    assert drop_calls == ["yo_reports"]
    assert brain.active_namespace == "finance"  # type: ignore[attr-defined]
