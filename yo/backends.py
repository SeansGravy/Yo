"""Runtime detection helpers for optional Yo backends."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from importlib import util as import_util
from shutil import which
import subprocess


def _safe_version(dist: str) -> str | None:
    """Return the installed version for *dist*, or ``None`` when unavailable."""

    try:
        return importlib_metadata.version(dist)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # pragma: no cover - defensive fallback
        return None


@dataclass(frozen=True)
class BackendStatus:
    """Represents the availability of a backend component."""

    available: bool
    message: str
    version: str | None = None


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
        version = _safe_version("milvus-lite") or _safe_version("pymilvus")
        detail = "Milvus Lite runtime detected."
        if version:
            detail += f" (version {version})"
        milvus_status = BackendStatus(True, detail, version)
    else:
        milvus_status = BackendStatus(
            False,
            "Install Milvus Lite support via `pip install pymilvus[milvus_lite]`.",
        )

    ollama_py_available = _module_available("ollama") and _module_available("langchain_ollama")
    if ollama_py_available:
        version = _safe_version("ollama") or _safe_version("langchain-ollama")
        detail = "Ollama Python bindings detected."
        if version:
            detail += f" (version {version})"
        ollama_python_status = BackendStatus(True, detail, version)
    else:
        ollama_python_status = BackendStatus(
            False,
            "Install the Ollama Python bindings via `pip install ollama langchain-ollama`.",
        )

    ollama_path = which("ollama")
    if ollama_path:
        version_info: str | None = None
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        except Exception:  # pragma: no cover - best effort only
            result = None

        if result and result.returncode == 0:
            version_info = (result.stdout or result.stderr).strip() or None

        detail = f"Ollama CLI available at {ollama_path}."
        if version_info:
            detail += f" ({version_info})"
        ollama_cli_status = BackendStatus(True, detail, version_info)
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
