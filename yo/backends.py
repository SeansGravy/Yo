"""Runtime detection helpers for optional Yo backends."""

from __future__ import annotations

from dataclasses import dataclass
import json
import httpx
from importlib import metadata as importlib_metadata
from importlib import util as import_util
from shutil import which
import subprocess
import os
from typing import Iterable, Sequence, Any, AsyncIterator

from yo.config import (
    Config,
    DEFAULT_EMBED_MODEL_SPEC,
    DEFAULT_MODEL_SPEC,
    get_config,
    parse_model_spec,
)
from yo.logging_utils import get_logger

LOGGER = get_logger(__name__)

FALLBACK_PROVIDERS: Sequence[str] = ("ollama", "openai", "anthropic")
DEFAULT_MODEL_MAP = {
    "chat": {
        "ollama": parse_model_spec(DEFAULT_MODEL_SPEC)[1],
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku",
    },
    "embedding": {
        "ollama": parse_model_spec(DEFAULT_EMBED_MODEL_SPEC)[1],
        "openai": "text-embedding-3-small",
        "anthropic": "claude-3-embed",
    },
}


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
    # python bindings
    ollama_python: BackendStatus
    # CLI executable
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


@dataclass(frozen=True)
class ModelSelection:
    """Result of running the centralised model selector."""

    task_type: str
    provider: str
    model: str
    spec: str
    namespace: str | None
    source: str
    fallback: bool = False
    reason: str | None = None


def _provider_available(provider: str, task_type: str, backends: BackendSummary) -> bool:
    provider = provider.lower()
    if provider == "ollama":
        return backends.ollama_python.available and backends.ollama_cli.available
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        return bool(api_key and _module_available("openai"))
    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        return bool(api_key and _module_available("anthropic"))
    return False


def _fallback_candidates(preferred: str) -> Iterable[str]:
    preferred = preferred.lower()
    seen = set()
    order = [preferred] + [p for p in FALLBACK_PROVIDERS if p != preferred]
    for provider in order:
        if provider not in seen:
            seen.add(provider)
            yield provider


def _default_model_for(provider: str, task_type: str) -> str:
    provider = provider.lower()
    task = task_type.lower()
    return DEFAULT_MODEL_MAP.get(task, {}).get(provider, "")


def _extract_ollama_chunk(payload: dict[str, Any]) -> str:
    """Extract a text chunk from an Ollama response payload."""

    chunk = payload.get("response") or ""
    if chunk:
        return str(chunk)

    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content", "")
        if content:
            return str(content)
    return ""


def run_ollama_chat(
    model: str,
    prompt: str,
    *,
    stream: bool = False,
    base_url: str | None = None,
    timeout: float = 30.0,
) -> str:
    """Call the Ollama /api/generate endpoint and return aggregated text."""

    base = base_url or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    endpoint = f"{base.rstrip('/')}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": stream}
    text_parts: list[str] = []

    try:
        if stream:
            with httpx.stream("POST", endpoint, json=payload, timeout=timeout) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        LOGGER.warning("Unable to decode Ollama stream chunk: %s", line)
                        continue
                    chunk = _extract_ollama_chunk(data)
                    if chunk:
                        text_parts.append(chunk)
        else:
            response = httpx.post(endpoint, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            chunk = _extract_ollama_chunk(data)
            if chunk:
                text_parts.append(chunk)
    except httpx.HTTPError as exc:
        LOGGER.warning("Ollama request failed: %s", exc)
    except Exception as exc:  # pragma: no cover - defensive path
        LOGGER.warning("Unexpected error contacting Ollama: %s", exc)

    return "".join(text_parts)


async def stream_ollama_chat(
    model: str,
    prompt: str,
    *,
    base_url: str | None = None,
    timeout: float = 30.0,
) -> AsyncIterator[str]:
    """Yield streaming chat tokens from the Ollama /api/generate endpoint."""

    base = base_url or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    endpoint = f"{base.rstrip('/')}/api/generate"
    payload = {"model": model, "prompt": prompt, "stream": True}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", endpoint, json=payload, timeout=timeout) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        LOGGER.warning("Unable to decode Ollama stream chunk: %s", line)
                        continue
                    chunk = _extract_ollama_chunk(data)
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        break
    except httpx.HTTPError as exc:
        LOGGER.warning("Ollama streaming request failed: %s", exc)
        return
    except Exception as exc:  # pragma: no cover - defensive path
        LOGGER.warning("Unexpected error during Ollama streaming request: %s", exc)
        return


def select_model(
    task_type: str,
    *,
    namespace: str | None = None,
    config: Config | None = None,
    backends: BackendSummary | None = None,
) -> ModelSelection:
    """Select the most appropriate backend model for ``task_type``."""

    if task_type not in {"chat", "embedding"}:
        raise ValueError(f"Unsupported task type '{task_type}'.")

    config = config or get_config(namespace=namespace)
    backends = backends or detect_backends()

    if task_type == "chat":
        candidate_spec = config.model_spec
        provider = config.model_provider
        model = config.model_name
        source = config.sources.get("model", "default")
    else:
        candidate_spec = config.embed_model_spec
        provider = config.embed_provider
        model = config.embed_name
        source = config.sources.get("embed_model", "default")

    if ":" not in candidate_spec and provider:
        candidate_spec = f"{provider}:{model}"

    chosen_provider = provider
    chosen_model = model
    chosen_spec = candidate_spec
    resolved_namespace = namespace or config.namespace

    if not _provider_available(provider, task_type, backends):
        fallback_reason = f"{provider} provider unavailable"
        for fallback_provider in _fallback_candidates(provider):
            if not _provider_available(fallback_provider, task_type, backends):
                continue
            chosen_provider = fallback_provider
            candidate_model = _default_model_for(fallback_provider, task_type)
            if not candidate_model:
                candidate_model = model
            chosen_model = candidate_model or model
            chosen_spec = f"{fallback_provider}:{chosen_model}"
            source = f"fallback:{fallback_provider}"
            LOGGER.info(
                "Model selection fallback for %s (namespace=%s) → provider=%s model=%s (%s)",
                task_type,
                resolved_namespace,
                chosen_provider,
                chosen_model,
                fallback_reason,
            )
            return ModelSelection(
                task_type=task_type,
                provider=chosen_provider,
                model=chosen_model,
                spec=chosen_spec,
                namespace=resolved_namespace,
                source=source,
                fallback=True,
                reason=fallback_reason,
            )

        raise RuntimeError(f"No available provider for {task_type} tasks (namespace={resolved_namespace}).")

    LOGGER.info(
        "Model selection for %s (namespace=%s) → provider=%s model=%s source=%s",
        task_type,
        resolved_namespace,
        chosen_provider,
        chosen_model,
        source,
    )
    return ModelSelection(
        task_type=task_type,
        provider=chosen_provider,
        model=chosen_model,
        spec=chosen_spec,
        namespace=resolved_namespace,
        source=source,
        fallback=False,
        reason=None,
    )


__all__ = [
    "BackendStatus",
    "BackendSummary",
    "ModelSelection",
    "detect_backends",
    "select_model",
    "run_ollama_chat",
    "stream_ollama_chat",
]
