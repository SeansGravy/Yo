from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from yo.backends import BackendStatus, BackendSummary, select_model
from yo.config import get_config


def _healthy_local_backends() -> BackendSummary:
    return BackendSummary(
        milvus=BackendStatus(True, "milvus", "1"),
        ollama_python=BackendStatus(True, "ollama py", "1"),
        ollama_cli=BackendStatus(True, "ollama cli", "1"),
    )


def test_select_model_falls_back_to_ollama(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YO_DATA_DIR", str(tmp_path))
    cfg = get_config(cli_args={"namespace": "default", "model": "openai:gpt-4o"})

    selection = select_model("chat", config=cfg, backends=_healthy_local_backends())

    assert selection.provider == "ollama"
    assert selection.fallback is True
    assert selection.model


def test_select_model_honours_ollama_spec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YO_DATA_DIR", str(tmp_path))
    cfg = get_config(cli_args={"namespace": "default", "model": "ollama:llama-custom"})

    selection = select_model("chat", config=cfg, backends=_healthy_local_backends())

    assert selection.provider == "ollama"
    assert selection.spec == "ollama:llama-custom"
    assert selection.fallback is False


def test_select_embedding_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YO_DATA_DIR", str(tmp_path))
    cfg = get_config(
        cli_args={
            "namespace": "default",
            "embed_model": "openai:text-embedding-3-small",
        }
    )

    selection = select_model("embedding", config=cfg, backends=_healthy_local_backends())

    assert selection.provider == "ollama"
    assert selection.model
    assert selection.spec.startswith("ollama:")
