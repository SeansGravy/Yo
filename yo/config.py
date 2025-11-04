"""Unified configuration loader for Yo.

This module centralises configuration coming from environment variables,
``.env`` files, CLI overrides, and namespace-specific metadata.  Use
``get_config`` to obtain an immutable :class:`Config` instance that reflects
the merged view for the active namespace.  Helpers are provided for updating
and resetting configuration so the CLI can expose ``yo config`` management
commands.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from dotenv import load_dotenv, set_key, unset_key

from yo.logging_utils import get_logger

LOGGER = get_logger(__name__)

ENV_FILE = Path(".env")
DEFAULT_NAMESPACE = "default"
DEFAULT_MODEL_SPEC = "ollama:llama3"
DEFAULT_EMBED_MODEL_SPEC = "ollama:nomic-embed-text"
DEFAULT_DB_FILENAME = "milvus_lite.db"

GLOBAL_CONFIG_KEYS = {
    "namespace": "YO_NAMESPACE",
    "model": "YO_MODEL",
    "embed_model": "YO_EMBED_MODEL",
    "db_uri": "YO_DB_URI",
    "data_dir": "YO_DATA_DIR",
}
NAMESPACE_CONFIG_KEYS = {"model", "embed_model"}

_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    global _DOTENV_LOADED
    if not _DOTENV_LOADED:
        load_dotenv(ENV_FILE, override=False)
        _DOTENV_LOADED = True


def parse_model_spec(spec: str, *, default_provider: str = "ollama") -> tuple[str, str]:
    """Return (provider, model_name) for ``spec``."""

    if not spec:
        return default_provider, ""
    cleaned = spec.strip()
    if ":" in cleaned:
        provider, name = cleaned.split(":", 1)
        return provider.strip().lower(), name.strip()
    return default_provider, cleaned


@dataclass(frozen=True)
class NamespaceConfig:
    model: str | None = None
    embed_model: str | None = None

    def as_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        if self.model:
            payload["model"] = self.model
        if self.embed_model:
            payload["embed_model"] = self.embed_model
        return payload


@dataclass(frozen=True)
class Config:
    namespace: str
    model_spec: str
    embed_model_spec: str
    model_provider: str
    model_name: str
    embed_provider: str
    embed_name: str
    db_uri: str
    data_dir: Path
    namespace_overrides: dict[str, NamespaceConfig] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def with_overrides(self, **updates: Any) -> "Config":
        return replace(self, **updates)


def _data_dir_from_sources(cli_args: Mapping[str, Any] | None) -> Path:
    if cli_args and cli_args.get("data_dir"):
        return Path(str(cli_args["data_dir"]))
    env_dir = os.environ.get(GLOBAL_CONFIG_KEYS["data_dir"])
    if env_dir:
        return Path(env_dir)
    return Path("data")


def _namespace_meta_path(data_dir: Path) -> Path:
    return data_dir / "namespace_meta.json"


def _namespace_state_path(data_dir: Path) -> Path:
    return data_dir / "namespace_state.json"


def _read_namespace_state(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        value = payload.get("active")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _load_namespace_meta(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Failed to parse namespace metadata at %s. Recreating.", path)
        return {}

    if not isinstance(payload, dict):
        return {}

    normalised: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            normalised[str(key)] = value
    return normalised


def _load_namespace_overrides(meta: Mapping[str, dict[str, Any]]) -> dict[str, NamespaceConfig]:
    overrides: dict[str, NamespaceConfig] = {}
    for namespace, entry in meta.items():
        config_payload = entry.get("config", {})
        if isinstance(config_payload, MutableMapping):
            overrides[namespace] = NamespaceConfig(
                model=config_payload.get("model"),
                embed_model=config_payload.get("embed_model"),
            )
    return overrides


def _ensure_namespace_entry(meta: dict[str, dict[str, Any]], namespace: str) -> None:
    entry = meta.setdefault(namespace, {})
    entry.setdefault("config", {})


def _save_namespace_meta(path: Path, meta: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)


def get_config(
    *,
    cli_args: Mapping[str, Any] | None = None,
    namespace: str | None = None,
) -> Config:
    """Return the merged configuration for the active namespace."""

    _load_dotenv_once()

    cli_args = cli_args or {}
    data_dir = _data_dir_from_sources(cli_args)
    data_dir.mkdir(parents=True, exist_ok=True)
    meta_path = _namespace_meta_path(data_dir)
    namespace_meta = _load_namespace_meta(meta_path)
    namespace_overrides = _load_namespace_overrides(namespace_meta)

    sources: dict[str, str] = {
        "namespace": "default",
        "model": "default",
        "embed_model": "default",
        "db_uri": "default",
    }

    model_spec = DEFAULT_MODEL_SPEC
    embed_spec = DEFAULT_EMBED_MODEL_SPEC
    db_uri = str(data_dir / DEFAULT_DB_FILENAME)

    # Environment overrides
    env_model = os.environ.get(GLOBAL_CONFIG_KEYS["model"])
    if env_model:
        model_spec = env_model
        sources["model"] = "env"

    env_embed = os.environ.get(GLOBAL_CONFIG_KEYS["embed_model"])
    if env_embed:
        embed_spec = env_embed
        sources["embed_model"] = "env"

    env_db_uri = os.environ.get(GLOBAL_CONFIG_KEYS["db_uri"])
    if env_db_uri:
        db_uri = env_db_uri
        sources["db_uri"] = "env"

    state_namespace = _read_namespace_state(_namespace_state_path(data_dir))

    resolved_namespace = DEFAULT_NAMESPACE
    if cli_args.get("namespace"):
        resolved_namespace = str(cli_args["namespace"]).strip() or DEFAULT_NAMESPACE
        sources["namespace"] = "cli"
    elif namespace:
        resolved_namespace = str(namespace).strip() or DEFAULT_NAMESPACE
        sources["namespace"] = "param"
    elif os.environ.get(GLOBAL_CONFIG_KEYS["namespace"]):
        resolved_namespace = str(os.environ[GLOBAL_CONFIG_KEYS["namespace"]]).strip() or DEFAULT_NAMESPACE
        sources["namespace"] = "env"
    elif state_namespace:
        resolved_namespace = state_namespace
        sources["namespace"] = "state"

    resolved_namespace = resolved_namespace or DEFAULT_NAMESPACE
    _ensure_namespace_entry(namespace_meta, resolved_namespace)

    # Namespace overrides
    ns_override = namespace_overrides.get(resolved_namespace)
    if ns_override:
        if ns_override.model:
            model_spec = ns_override.model
            sources["model"] = f"namespace:{resolved_namespace}"
        if ns_override.embed_model:
            embed_spec = ns_override.embed_model
            sources["embed_model"] = f"namespace:{resolved_namespace}"

    # CLI overrides
    if cli_args.get("model"):
        model_spec = str(cli_args["model"])
        sources["model"] = "cli"

    if cli_args.get("embed_model"):
        embed_spec = str(cli_args["embed_model"])
        sources["embed_model"] = "cli"

    if cli_args.get("db_uri"):
        db_uri = str(cli_args["db_uri"])
        sources["db_uri"] = "cli"

    model_provider, model_name = parse_model_spec(model_spec)
    embed_provider, embed_name = parse_model_spec(embed_spec)

    namespace_meta.setdefault(resolved_namespace, {}).setdefault(
        "config",
        {
            "model": model_spec,
            "embed_model": embed_spec,
        },
    )

    return Config(
        namespace=resolved_namespace,
        model_spec=model_spec,
        embed_model_spec=embed_spec,
        model_provider=model_provider,
        model_name=model_name,
        embed_provider=embed_provider,
        embed_name=embed_name,
        db_uri=db_uri,
        data_dir=data_dir,
        namespace_overrides=namespace_overrides,
        sources=sources,
    )


def update_config_value(
    key: str,
    value: str,
    *,
    namespace: str | None = None,
    data_dir: Path | None = None,
) -> None:
    """Persist a configuration value globally or for a namespace."""

    key = key.strip().lower()
    if namespace and key not in NAMESPACE_CONFIG_KEYS:
        raise ValueError(f"Namespace overrides do not support '{key}'.")

    if namespace:
        namespace = namespace.strip() or DEFAULT_NAMESPACE
        data_dir = data_dir or _data_dir_from_sources({"data_dir": os.environ.get(GLOBAL_CONFIG_KEYS["data_dir"])})
        meta_path = _namespace_meta_path(data_dir)
        meta = _load_namespace_meta(meta_path)
        _ensure_namespace_entry(meta, namespace)
        config_block = meta.setdefault(namespace, {}).setdefault("config", {})
        config_block[key] = value
        _save_namespace_meta(meta_path, meta)
        LOGGER.info("Updated namespace config %s.%s=%s", namespace, key, value)
        return

    env_key = GLOBAL_CONFIG_KEYS.get(key)
    if not env_key:
        raise ValueError(f"Unsupported configuration key '{key}'.")

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(ENV_FILE), env_key, value)
    LOGGER.info("Set global config %s=%s", env_key, value)


def reset_config(
    keys: Iterable[str] | None = None,
    *,
    namespace: str | None = None,
    data_dir: Path | None = None,
) -> None:
    """Reset configuration values to defaults."""

    if namespace:
        namespace = namespace.strip() or DEFAULT_NAMESPACE
        data_dir = data_dir or _data_dir_from_sources({"data_dir": os.environ.get(GLOBAL_CONFIG_KEYS["data_dir"])})
        meta_path = _namespace_meta_path(data_dir)
        meta = _load_namespace_meta(meta_path)
        if namespace not in meta:
            return
        config_block = meta.setdefault(namespace, {}).setdefault("config", {})
        if not keys:
            config_block.clear()
        else:
            for key in keys:
                if key in config_block:
                    config_block.pop(key, None)
        _save_namespace_meta(meta_path, meta)
        LOGGER.info("Reset namespace config %s (keys=%s)", namespace, list(keys or ["*"]))
        return

    targets = list(keys) if keys else list(GLOBAL_CONFIG_KEYS)
    for key in targets:
        env_key = GLOBAL_CONFIG_KEYS.get(key)
        if not env_key:
            continue
        unset_key(str(ENV_FILE), env_key)
    LOGGER.info("Reset global config keys=%s", targets)


def serialize_config(config: Config) -> dict[str, Any]:
    """Return a JSON-serialisable view of a :class:`Config`."""

    return {
        "namespace": config.namespace,
        "model": {
            "spec": config.model_spec,
            "provider": config.model_provider,
            "name": config.model_name,
            "source": config.sources.get("model"),
        },
        "embedding": {
            "spec": config.embed_model_spec,
            "provider": config.embed_provider,
            "name": config.embed_name,
            "source": config.sources.get("embed_model"),
        },
        "db_uri": config.db_uri,
        "data_dir": str(config.data_dir),
        "sources": dict(config.sources),
        "namespace_overrides": {
            ns: override.as_dict()
            for ns, override in sorted(config.namespace_overrides.items())
            if override.as_dict()
        },
    }


__all__ = [
    "Config",
    "NamespaceConfig",
    "DEFAULT_MODEL_SPEC",
    "DEFAULT_EMBED_MODEL_SPEC",
    "get_config",
    "parse_model_spec",
    "reset_config",
    "serialize_config",
    "update_config_value",
]
