"""Runtime detection helpers for optional Yo backends."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import util as import_util
from shutil import which


@dataclass(frozen=True)
class BackendStatus:
    """Represents the availability of a backend component."""

    available: bool
    message: str


@dataclass(frozen=True)
class BackendSummary:
    """Aggregated status for the Milvus Lite and Ollama backends."""

    milvus: BackendStatus
    ollama_python: BackendStatus
    ollama_cli: BackendStatus


def _module_available(name: str) -> bool:
    """Return True when the given Python module can be imported."""

    return import_util.find_spec(name) is not None


def detect_backends() -> BackendSummary:
    """Detect the availability of optional backends and return diagnostics."""

    milvus_available = _module_available("milvus_lite") and _module_available("pymilvus")
    if milvus_available:
        milvus_status = BackendStatus(True, "Milvus Lite runtime detected.")
    else:
        milvus_status = BackendStatus(
            False,
            "Install Milvus Lite support via `pip install pymilvus[milvus_lite]`.",
        )

    ollama_py_available = _module_available("ollama") and _module_available("langchain_ollama")
    if ollama_py_available:
        ollama_python_status = BackendStatus(True, "Ollama Python bindings detected.")
    else:
        ollama_python_status = BackendStatus(
            False,
            "Install the Ollama Python bindings via `pip install ollama langchain-ollama`.",
        )

    ollama_path = which("ollama")
    if ollama_path:
        ollama_cli_status = BackendStatus(True, f"Ollama CLI available at {ollama_path}.")
    else:
        ollama_cli_status = BackendStatus(
            False,
            "Install the Ollama CLI from https://ollama.com/download and ensure it is on your PATH.",
        )

    return BackendSummary(
        milvus=milvus_status,
        ollama_python=ollama_python_status,
        ollama_cli=ollama_cli_status,
    )
