from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from yo.config import get_config, reset_config, serialize_config, update_config_value


def test_get_config_merges_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YO_DATA_DIR", str(tmp_path))
    meta_payload = {
        "research": {
            "config": {
                "model": "ollama:llama2",
                "embed_model": "ollama:nomic-embed-special",
            }
        }
    }
    (tmp_path / "namespace_meta.json").write_text(json.dumps(meta_payload), encoding="utf-8")
    monkeypatch.setenv("YO_MODEL", "ollama:llama3")

    cfg = get_config(cli_args={"namespace": "research"})
    assert cfg.namespace == "research"
    assert cfg.model_name == "llama2"
    assert cfg.sources["model"].startswith("namespace")
    assert cfg.embed_name == "nomic-embed-special"

    cfg_cli = get_config(cli_args={"namespace": "research", "model": "ollama:custom"})
    assert cfg_cli.model_name == "custom"
    assert cfg_cli.sources["model"] == "cli"


def test_namespace_config_update_and_reset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YO_DATA_DIR", str(tmp_path))

    update_config_value("model", "ollama:mixtral", namespace="experiments", data_dir=tmp_path)
    meta = json.loads((tmp_path / "namespace_meta.json").read_text(encoding="utf-8"))
    assert meta["experiments"]["config"]["model"] == "ollama:mixtral"

    reset_config(["model"], namespace="experiments", data_dir=tmp_path)
    meta_after = json.loads((tmp_path / "namespace_meta.json").read_text(encoding="utf-8"))
    assert "model" not in meta_after.get("experiments", {}).get("config", {})


def test_serialize_config_structure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YO_DATA_DIR", str(tmp_path))
    cfg = get_config(cli_args={"namespace": "default", "model": "ollama:llama3"})
    payload = serialize_config(cfg)

    assert payload["namespace"] == "default"
    assert payload["model"]["spec"] == "ollama:llama3"
    assert payload["embedding"]["provider"] == "ollama"
    assert payload["db_uri"]
