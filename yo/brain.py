"""Core Yo brain logic.

This module provides the main orchestration layer for the Yo CLI.  It handles
Milvus Lite lifecycle management, document ingestion, retrieval, summarisation,
and simple web-context caching for the optional web-aware mode.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from importlib import util as import_util
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, NoReturn

from yo.logging_utils import get_logger
from yo.config import Config as YoConfig, get_config
from yo.backends import select_model

try:  # pragma: no cover - dependency presence is validated in tests
    import chardet
except ImportError:  # pragma: no cover - handled dynamically
    chardet = None  # type: ignore[assignment]

try:  # pragma: no cover - optional network dependency
    import requests
except ImportError:  # pragma: no cover - handled dynamically
    requests = None  # type: ignore[assignment]

try:  # pragma: no cover - optional embedding dependency
    from langchain_ollama import OllamaEmbeddings
except ImportError:  # pragma: no cover - handled dynamically
    OllamaEmbeddings = None  # type: ignore[assignment]

try:  # pragma: no cover - optional splitter dependency
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover - handled dynamically
    RecursiveCharacterTextSplitter = None  # type: ignore[assignment]

try:  # pragma: no cover - optional client dependency
    from ollama import Client
except ImportError:  # pragma: no cover - handled dynamically
    Client = None  # type: ignore[assignment]

try:  # pragma: no cover - optional vector store dependency
    from pymilvus import (
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        connections,
        utility,
    )
except ImportError:  # pragma: no cover - handled dynamically
    Collection = CollectionSchema = DataType = FieldSchema = None  # type: ignore[assignment]
    connections = utility = None  # type: ignore[assignment]


try:  # pragma: no cover - optional imports are validated at runtime
    from langchain_community.document_loaders import (
        TextLoader,
        UnstructuredExcelLoader,
        UnstructuredPDFLoader,
    )
except ImportError:  # pragma: no cover - handled during ingestion
    TextLoader = None  # type: ignore[assignment]
    UnstructuredExcelLoader = None
    UnstructuredPDFLoader = None

EMBED_DIM = 768
CACHE_TTL = timedelta(hours=24)

OLLAMA_AVAILABLE = Client is not None and OllamaEmbeddings is not None
SPLITTER_AVAILABLE = RecursiveCharacterTextSplitter is not None
MILVUS_AVAILABLE = connections is not None and utility is not None

TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".go",
    ".java",
    ".rb",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".log",
}
PDF_SUFFIXES = {".pdf"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls"}


class IngestionError(ValueError):
    """Raised when document ingestion cannot proceed for a specific reason."""


class MissingDependencyError(IngestionError):
    """Raised when a required optional dependency is unavailable."""


class YoBrain:
    """Primary orchestration layer for Yo."""

    def __init__(
        self,
        data_dir: Path | str | None = None,
        model_name: str | None = None,
        embed_model: str | None = None,
        namespace: str | None = None,
        *,
        config: YoConfig | None = None,
    ) -> None:
        self._logger = get_logger(__name__)

        cli_overrides: Dict[str, Any] = {}
        if data_dir:
            cli_overrides["data_dir"] = str(data_dir)
        if namespace:
            cli_overrides["namespace"] = namespace
        if model_name:
            cli_overrides["model"] = model_name
        if embed_model:
            cli_overrides["embed_model"] = embed_model

        if config is None:
            config = get_config(cli_args=cli_overrides or None, namespace=namespace)
        elif cli_overrides:
            merged = cli_overrides.copy()
            merged.setdefault("namespace", config.namespace)
            config = get_config(cli_args=merged, namespace=config.namespace)

        self.config = config
        self.data_dir = config.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.recover_dir = self.data_dir / "recoveries"
        self.recover_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.data_dir / "namespace_meta.json"
        self.state_path = self.data_dir / "namespace_state.json"

        self.db_path = self._resolve_db_path(config.db_uri)
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except FileNotFoundError:
            pass

        if not OLLAMA_AVAILABLE:
            raise RuntimeError(
                "Ollama runtime unavailable. Install `ollama` and `langchain-ollama` to enable YoBrain."
            )
        if not SPLITTER_AVAILABLE:
            raise RuntimeError(
                "Document splitting requires `langchain-text-splitters`. Install it via `pip install langchain-text-splitters`."
            )
        if not MILVUS_AVAILABLE:
            raise RuntimeError(
                "Milvus Lite dependencies missing. Install `pymilvus` (and `milvus-lite`) before using Yo."
            )

        self._connect_milvus()

        preferred_namespace = self.config.namespace
        resolved_namespace = self._load_active_namespace(preferred=preferred_namespace)
        if resolved_namespace != self.config.namespace:
            self.config = get_config(
                cli_args={
                    "namespace": resolved_namespace,
                    "data_dir": str(self.data_dir),
                }
            )

        self.active_namespace = resolved_namespace
        self.cache_path = self._cache_path_for(self.active_namespace)

        self._initialise_models()

        self._logger.info(
            "YoBrain ready (namespace=%s, provider=%s, model=%s, db=%s)",
            self.active_namespace,
            self.model_provider,
            self.model_name,
            self.db_path,
        )

    def _resolve_db_path(self, uri: str) -> Path:
        if not uri:
            return (self.data_dir / "milvus_lite.db").resolve()
        cleaned = uri.strip()
        if cleaned.startswith("sqlite:///"):
            cleaned = cleaned[len("sqlite:///") :]
        path = Path(cleaned)
        if path.is_absolute():
            return path
        return path.resolve()

    def _initialise_models(self) -> None:
        chat_selection = select_model(
            "chat",
            namespace=self.active_namespace,
            config=self.config,
        )
        embed_selection = select_model(
            "embedding",
            namespace=self.active_namespace,
            config=self.config,
        )

        self.model_selection = chat_selection
        self.embedding_selection = embed_selection
        self.model_provider = chat_selection.provider
        self.embed_provider = embed_selection.provider

        if self.model_provider != "ollama" or self.embed_provider != "ollama":
            raise RuntimeError(
                "Only the Ollama provider is currently supported by YoBrain."
            )

        self.model_name = chat_selection.model
        self.embed_model = embed_selection.model

        self.client = Client()  # type: ignore[operator]
        self.embeddings = OllamaEmbeddings(model=self.embed_model)  # type: ignore[operator]

    # ------------------------------------------------------------------
    # Milvus helpers
    # ------------------------------------------------------------------
    def _connect_milvus(self) -> None:
        """Connect to Milvus Lite, handling locked database recovery."""

        lock_path = self.db_path.parent / ".milvus_lite.db.lock"
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass

        try:
            connections.disconnect(alias="default")
        except Exception:
            pass

        try:
            connections.connect(alias="default", uri=str(self.db_path))
            return
        except Exception as exc:  # pragma: no cover - defensive path
            message = str(exc).lower()
            if "locked" not in message and "database" not in message:
                raise

        # Database is likely locked – rename it and retry.
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.recover_dir / f"milvus_lite_recover_{timestamp}.db"
        if self.db_path.exists():
            self.db_path.replace(backup_path)
            self._prune_recoveries(keep=3)
            print(
                "⚠️  Milvus Lite database was locked. "
                f"Moved existing file to {backup_path.name} and recreating."
            )

        connections.connect(alias="default", uri=str(self.db_path))

    def _prune_recoveries(self, keep: int = 3) -> None:
        backups = sorted(self.recover_dir.glob("milvus_lite_recover_*.db"))
        while len(backups) > keep:
            oldest = backups.pop(0)
            try:
                oldest.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _collection_name(namespace: str) -> str:
        return f"yo_{namespace}"

    def _cache_path_for(self, namespace: str) -> Path:
        if namespace == "default":
            return self.data_dir / "web_cache.json"
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", namespace)
        return self.data_dir / f"web_cache_{safe}.json"

    def _load_namespace_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                raw_state = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}
        if isinstance(raw_state, dict):
            return raw_state
        return {}

    def _save_namespace_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)

    def _load_active_namespace(self, preferred: str | None = None) -> str:
        state = self._load_namespace_state()
        candidates: List[str] = []
        if preferred:
            candidates.append(preferred)
        stored = str(state.get("active", "") or "").strip()
        if stored:
            candidates.append(stored)
        candidates.extend(["default", "Default", "" ])

        try:
            available = self.ns_list(silent=True)
        except Exception:
            available = []

        for candidate in candidates:
            candidate = str(candidate or "default").strip() or "default"
            if not available:
                return candidate
            if candidate in available:
                return candidate

        return available[0] if available else "default"

    def _set_active_namespace(self, namespace: str) -> None:
        state = self._load_namespace_state()
        state["active"] = namespace
        self._save_namespace_state(state)

        self.active_namespace = namespace
        self.cache_path = self._cache_path_for(namespace)
        self.config = get_config(
            cli_args={
                "namespace": namespace,
                "data_dir": str(self.data_dir),
            }
        )
        self._initialise_models()
        self._logger.info("Active namespace switched to %s", namespace)

    def _ensure_collection(self, namespace: str) -> Collection:
        name = self._collection_name(namespace)
        if name in utility.list_collections():
            return Collection(name)

        schema = CollectionSchema(
            fields=[
                FieldSchema(
                    name="id",
                    dtype=DataType.INT64,
                    is_primary=True,
                    auto_id=False,
                ),
                FieldSchema(
                    name="text",
                    dtype=DataType.VARCHAR,
                    max_length=65535,
                ),
                FieldSchema(
                    name="source",
                    dtype=DataType.VARCHAR,
                    max_length=1024,
                ),
                FieldSchema(
                    name="embedding",
                    dtype=DataType.FLOAT_VECTOR,
                    dim=EMBED_DIM,
                ),
            ],
            description=f"Yo collection for namespace {namespace}",
        )
        collection = Collection(name, schema)
        collection.create_index(
            field_name="embedding",
            index_params={"index_type": "AUTOINDEX", "metric_type": "IP"},
        )
        return collection

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------
    def _load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}

        try:
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                cache = json.load(fh)
        except (json.JSONDecodeError, OSError):
            self._logger.warning("⚠️  Cache file was corrupted. Resetting web cache (%s).", self.cache_path)
            try:
                self.cache_path.unlink()
            except FileNotFoundError:
                pass
            return {}

        pruned = False
        for query, entry in list(cache.items()):
            if not self._cache_fresh(entry):
                cache.pop(query, None)
                pruned = True

        if pruned:
            self._save_cache(cache)

        return cache

    def _save_cache(self, cache: dict) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2)

    def _load_namespace_meta(self) -> Dict[str, Dict[str, Any]]:
        if not self.meta_path.exists():
            return {}

        try:
            with open(self.meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}

        if not isinstance(meta, dict):  # pragma: no cover - defensive
            return {}

        return {str(key): value for key, value in meta.items() if isinstance(value, dict)}

    def _save_namespace_meta(self, meta: Dict[str, Dict[str, Any]]) -> None:
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)

    def _update_namespace_meta(
        self,
        namespace: str,
        *,
        documents: int | None = None,
        chunks: int | None = None,
    ) -> None:
        meta = self._load_namespace_meta()
        entry = meta.setdefault(namespace, {})
        now = datetime.now()
        entry["last_ingested"] = now.isoformat()
        config_block = entry.setdefault("config", {})
        config_block["model"] = getattr(self, "model_selection", None).spec if getattr(self, "model_selection", None) else self.config.model_spec
        config_block["embed_model"] = getattr(self, "embedding_selection", None).spec if getattr(self, "embedding_selection", None) else self.config.embed_model_spec
        previous_documents = int(entry.get("documents", 0) or 0)
        previous_chunks = int(entry.get("chunks", 0) or 0)
        documents_added = int(documents or 0)
        chunks_added = int(chunks or 0)
        if documents is not None:
            entry["documents"] = previous_documents + documents_added
        if chunks is not None:
            entry["chunks"] = previous_chunks + chunks_added
        entry["documents_delta"] = documents_added
        entry["chunks_delta"] = chunks_added
        total_documents = int(entry.get("documents", previous_documents))
        total_chunks = int(entry.get("chunks", previous_chunks))
        entry["ingest_runs"] = int(entry.get("ingest_runs", 0)) + 1

        if previous_documents > 0 and documents_added:
            growth_percent = (documents_added / previous_documents) * 100
        elif documents_added and previous_documents == 0:
            growth_percent = 100.0
        else:
            growth_percent = 0.0
        entry["growth_percent"] = growth_percent

        history = entry.setdefault("history", [])
        history.append(
            {
                "timestamp": now.isoformat(),
                "documents_added": documents_added,
                "chunks_added": chunks_added,
                "documents_total": total_documents,
                "chunks_total": total_chunks,
                "documents_previous": previous_documents,
                "chunks_previous": previous_chunks,
                "growth_percent": growth_percent,
            }
        )
        if len(history) > 100:
            del history[:-100]

        self._save_namespace_meta(meta)

    def _rollback_insert(self, collection: Collection, ids: List[int]) -> None:
        if not ids:
            return
        expr = "id in [" + ", ".join(str(idx) for idx in ids) + "]"
        try:
            collection.delete(expr=expr)
            collection.flush()
            self._logger.warning(
                "↩️  Rolled back %s partial records from %s",
                len(ids),
                getattr(collection, "name", "<unknown>"),
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            self._logger.error(
                "Rollback failed for %s: %s",
                getattr(collection, "name", "<unknown>"),
                exc,
            )

    def _cache_fresh(self, entry: dict) -> bool:
        if not entry:
            return False
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
        except Exception:
            return False
        return datetime.now() - ts < CACHE_TTL

    def _fetch_web(self, query: str) -> List[str]:
        if requests is None:
            return [
                "Web lookup unavailable: install the `requests` package to enable live context."
            ]

        cache = self._load_cache()
        cached = cache.get(query)
        if cached and self._cache_fresh(cached):
            print("💾 Using cached web context…")
            return cached["results"]

        print("🌐 Fetching live web context…")
        try:
            url = "https://duckduckgo.com/html/"
            params = {"q": query}
            resp = requests.get(
                url,
                params=params,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            resp.raise_for_status()
        except Exception as exc:  # pragma: no cover - network failure path
            return [f"Web lookup failed: {exc}"]

        snippets = re.findall(
            r'<a rel="nofollow" class="result__a".*?>(.*?)</a>', resp.text
        )
        cleaned = [re.sub(r"<.*?>", "", snippet) for snippet in snippets[:3]]
        cache[query] = {
            "timestamp": datetime.now().isoformat(),
            "results": cleaned,
        }
        self._save_cache(cache)
        return cleaned

    def _namespace_stats(self, namespace: str) -> Dict[str, Any]:
        stats: Dict[str, Any] = {"records": None}
        coll_name = self._collection_name(namespace)
        try:
            if coll_name in utility.list_collections():
                collection = Collection(coll_name)
                stats["records"] = int(collection.num_entities)
        except Exception:
            stats["records"] = None
        return stats

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------
    def ingest(self, source: str, namespace: str = "default") -> dict[str, Any] | None:
        namespace = (namespace or "default").strip() or "default"
        start = time.perf_counter()
        path = Path(source)
        if not path.exists():
            self._logger.error(
                "⚠️  Ingestion aborted — source path not found (namespace=%s, source=%s)",
                namespace,
                source,
            )
            raise FileNotFoundError(f"Source path not found: {source}")

        self._logger.info(
            "🚚 Ingestion requested (namespace=%s, source=%s)",
            namespace,
            source,
        )
        try:
            documents = self._load_documents(path)
        except (MissingDependencyError, IngestionError):
            raise
        except Exception as exc:
            self._logger.exception(
                "⚠️  Failed to load documents (namespace=%s, source=%s)",
                namespace,
                source,
            )
            raise IngestionError(f"Failed to load documents from {source}: {exc}") from exc

        if not documents:
            self._logger.warning(
                "⚠️  No ingestible documents found (namespace=%s, source=%s)",
                namespace,
                source,
            )
            return None

        chunk_size = int(os.environ.get("YO_CHUNK_SIZE", "800") or "800")
        chunk_overlap = int(os.environ.get("YO_CHUNK_OVERLAP", "120") or "120")
        chunk_size = max(200, min(chunk_size, 2000))
        chunk_overlap = max(0, min(chunk_overlap, chunk_size // 2))
        try:
            splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            chunks = splitter.split_documents(documents)
        except Exception as exc:
            self._logger.exception(
                "⚠️  Chunk generation failed (namespace=%s, documents=%s)",
                namespace,
                len(documents),
            )
            raise IngestionError("Failed to split documents for ingestion.") from exc

        self._logger.info(
            "🧩 Created %s chunks (namespace=%s, documents=%s)",
            len(chunks),
            namespace,
            len(documents),
        )

        collection = self._ensure_collection(namespace)

        payloads = [chunk.page_content for chunk in chunks]
        sources = [str(chunk.metadata.get("source", "")) for chunk in chunks]
        try:
            embeddings = self.embeddings.embed_documents(payloads)
        except Exception as exc:
            self._logger.exception(
                "⚠️  Embedding generation failed (namespace=%s, records=%s)",
                namespace,
                len(payloads),
            )
            raise IngestionError(
                "Failed to generate embeddings. Ensure the Ollama runtime is healthy."
            ) from exc

        base_id = int(time.time() * 1000)
        ids = [base_id + idx for idx in range(len(chunks))]

        try:
            collection.insert([ids, payloads, sources, embeddings])
            collection.flush()
        except Exception as exc:
            self._logger.exception(
                "⚠️  Milvus insert failed (namespace=%s, records=%s)",
                namespace,
                len(ids),
            )
            self._rollback_insert(collection, ids)
            raise IngestionError(
                f"Failed to persist chunks into namespace '{namespace}'. "
                "Check Milvus Lite configuration and retry."
            ) from exc

        duration = time.perf_counter() - start
        summary = {
            "namespace": namespace,
            "documents_ingested": len(documents),
            "chunks_ingested": len(chunks),
            "duration_seconds": round(duration, 3),
        }
        self._update_namespace_meta(
            namespace,
            documents=len(documents),
            chunks=len(chunks),
        )
        self._logger.info(
            "✅ Ingestion complete (namespace=%s, documents=%s, chunks=%s, duration=%.3fs)",
            namespace,
            len(documents),
            len(chunks),
            duration,
        )
        return summary

    def ask(self, question: str, namespace: str = "default", web: bool = False) -> str:
        if not question:
            raise ValueError("A question is required for ask().")

        coll_name = self._collection_name(namespace)
        memory_context, citations = self._search_memory(coll_name, question)

        context_parts = ["[Memory Results]\n" + memory_context]

        if web:
            web_snippets = self._fetch_web(question)
            context_parts.append("[Web Results]\n" + "\n".join(web_snippets))

        combined_context = "\n\n".join(context_parts)
        print("\n📚 Context Used:\n")
        print(combined_context)

        answer = self._synthesise_answer(question, combined_context)
        print("\n💬 Yo says:\n")
        print(answer)
        return answer

    def summarize(self, namespace: str = "default") -> str:
        coll_name = self._collection_name(namespace)
        if coll_name not in utility.list_collections():
            raise ValueError(f"Namespace '{namespace}' does not exist.")

        collection = Collection(coll_name)
        collection.load()
        records = collection.query(
            expr="id >= 0",
            output_fields=["text"],
            limit=500,
        )
        if not records:
            raise ValueError(f"Namespace '{namespace}' is empty.")

        combined = "\n\n".join(row["text"] for row in records)
        prompt = (
            "Summarize the following knowledge base for future reference. "
            "Highlight key facts and topics.\n\n" + combined
        )
        response = self.client.generate(model=self.model_name, prompt=prompt)
        summary = response["response"]
        print("\n🧾 Summary:\n")
        print(summary)
        return summary

    def ns_list(self, *, silent: bool = False) -> List[str]:
        namespaces = []
        for name in utility.list_collections():
            if name.startswith("yo_"):
                namespaces.append(name[len("yo_"):])

        sorted_names = sorted(namespaces)

        if silent:
            return sorted_names

        active = getattr(self, "active_namespace", "default")
        if sorted_names:
            print("🗂️  Available namespaces:")
            for ns in sorted_names:
                marker = " (active)" if ns == active else ""
                print(f" - {ns}{marker}")
        else:
            print("(no namespaces found)")

        return sorted_names

    def namespace_activity(self) -> Dict[str, Dict[str, Any]]:
        meta = self._load_namespace_meta()
        activity: Dict[str, Dict[str, Any]] = {}
        for ns in self.ns_list(silent=True):
            entry = meta.get(ns, {})
            history = entry.get("history") or []
            last_history = history[-1] if history else {}
            stats: Dict[str, Any] = {
                "last_ingested": entry.get("last_ingested"),
                "documents": entry.get("documents", 0),
                "chunks": entry.get("chunks", 0),
                "documents_delta": last_history.get("documents_added", entry.get("documents_delta", 0)),
                "chunks_delta": last_history.get("chunks_added", entry.get("chunks_delta", 0)),
                "growth_percent": last_history.get("growth_percent", entry.get("growth_percent", 0.0)),
                "ingest_runs": entry.get("ingest_runs", len(history)),
            }
            stats.update(self._namespace_stats(ns))
            activity[ns] = stats
        return activity

    def namespace_drift(self, since: timedelta) -> Dict[str, Dict[str, Any]]:
        meta = self._load_namespace_meta()
        threshold = datetime.now() - since
        drift: Dict[str, Dict[str, Any]] = {}

        for ns in self.ns_list(silent=True):
            entry = meta.get(ns, {})
            history = entry.get("history") or []
            documents_added = 0
            chunks_added = 0
            ingests = 0
            baseline_documents: Optional[int] = None
            baseline_chunks: Optional[int] = None

            for item in history:
                ts_raw = item.get("timestamp")
                try:
                    ts = datetime.fromisoformat(ts_raw)
                except Exception:
                    continue
                if ts < threshold:
                    continue
                ingests += 1
                documents_added += int(item.get("documents_added", 0) or 0)
                chunks_added += int(item.get("chunks_added", 0) or 0)
                if baseline_documents is None:
                    baseline_documents = int(item.get("documents_previous", 0) or 0)
                    baseline_chunks = int(item.get("chunks_previous", 0) or 0)

            total_documents = int(entry.get("documents", 0) or 0)
            total_chunks = int(entry.get("chunks", 0) or 0)

            if baseline_documents is None:
                baseline_documents = max(total_documents - documents_added, 0)
            if baseline_chunks is None:
                baseline_chunks = max(total_chunks - chunks_added, 0)

            if baseline_documents > 0 and documents_added:
                growth_percent = (documents_added / baseline_documents) * 100
            elif documents_added and baseline_documents == 0:
                growth_percent = 100.0
            else:
                growth_percent = 0.0

            stats: Dict[str, Any] = {
                "documents_added": documents_added,
                "chunks_added": chunks_added,
                "documents_total": total_documents,
                "chunks_total": total_chunks,
                "growth_percent": growth_percent,
                "ingests": ingests,
                "last_ingested": entry.get("last_ingested"),
                "window_seconds": since.total_seconds(),
            }
            stats.update(self._namespace_stats(ns))
            drift[ns] = stats
        return drift

    def ns_switch(self, namespace: str) -> str:
        coll_name = self._collection_name(namespace)
        if coll_name not in utility.list_collections():
            raise ValueError(f"Namespace '{namespace}' does not exist.")
        self._set_active_namespace(namespace)
        self._logger.info("🧭 Active namespace switched to %s", namespace)
        return namespace

    def ns_purge(self, namespace: str) -> None:
        coll_name = self._collection_name(namespace)
        if coll_name not in utility.list_collections():
            raise ValueError(f"Namespace '{namespace}' does not exist.")
        utility.drop_collection(coll_name)
        self._logger.info("🗑️  Deleted namespace '%s'.", namespace)
        meta = self._load_namespace_meta()
        if meta.pop(namespace, None) is not None:
            self._save_namespace_meta(meta)

        if getattr(self, "active_namespace", "default") == namespace:
            remaining = [ns for ns in self.ns_list(silent=True) if ns != namespace]
            if "default" in remaining:
                fallback = "default"
            elif remaining:
                fallback = remaining[0]
            else:
                fallback = "default"
            self._set_active_namespace(fallback)

    def ns_delete(self, namespace: str) -> None:
        self.ns_purge(namespace)

    def _list_cache(self) -> None:
        cache = self._load_cache()
        if not cache:
            print("ℹ️  Cache is empty.")
            return
        print("🧾 Cached queries:")
        for query, payload in cache.items():
            print(f" - {query} (cached {payload.get('timestamp', 'unknown')})")

    def _clear_cache(self) -> None:
        if self.cache_path.exists():
            self.cache_path.unlink()
            print("🧹 Cache cleared.")
        else:
            print("ℹ️  Cache file not found.")

    def compact(self) -> None:
        if not self.db_path.exists():
            print("ℹ️  No database file to compact.")
            return
        before = self.db_path.stat().st_size
        conn = sqlite3.connect(self.db_path)
        conn.execute("VACUUM;")
        conn.close()
        after = self.db_path.stat().st_size
        delta = before - after
        print(
            f"VACUUM complete. Size reduced by {delta / (1024**2):.2f} MiB "
            f"({before / (1024**2):.2f} → {after / (1024**2):.2f} MiB)."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _detect_encoding(self, path: Path) -> Optional[str]:
        """Best-effort encoding detection using chardet for binary files."""

        if chardet is None or not hasattr(chardet, "detect"):
            return None

        try:
            with path.open("rb") as handle:
                sample = handle.read(4096)
        except OSError:
            return None

        if not sample:
            return None

        try:
            result = chardet.detect(sample)
        except Exception:  # pragma: no cover - defensive
            return None

        encoding = result.get("encoding") if isinstance(result, dict) else None
        if encoding and isinstance(encoding, str):
            return encoding
        return None

    def _ensure_dependency(self, module: str, hint: str) -> None:
        """Raise ``MissingDependencyError`` if *module* cannot be imported."""

        if import_util.find_spec(module) is None:
            raise MissingDependencyError(hint)

    def _ensure_chardet(self) -> None:
        if chardet is None or not hasattr(chardet, "detect"):
            raise MissingDependencyError(
                "Install `chardet` to enable encoding detection for PDF and spreadsheet ingestion."
            )

    def _handle_loader_failure(
        self,
        file_path: Path,
        exc: Exception,
        dependency_hint: str,
        context: str,
    ) -> "NoReturn":
        """Convert loader exceptions into rich ingestion feedback."""

        message = str(exc)
        lowered = message.lower()
        if "binary files are not supported" in lowered:
            guidance = (
                f"{context} {file_path.name}: {message}. "
                "This usually means the loader received non-text bytes — "
                "for example when downloading from GitHub without using the raw asset — "
                f"or that extra parsing dependencies are required. {dependency_hint}"
            )
            raise IngestionError(guidance) from exc

        raise IngestionError(f"{context} {file_path.name}: {message}") from exc

    def _load_file_documents(self, file_path: Path) -> List:
        suffix = file_path.suffix.lower()
        if suffix in TEXT_SUFFIXES:
            if TextLoader is None:
                raise MissingDependencyError(
                    "Text ingestion requires `langchain-community`. Install it via `pip install langchain-community`."
                )
            encoding = self._detect_encoding(file_path)
            kwargs: Dict[str, Any] = {"autodetect_encoding": True}
            if encoding:
                kwargs["encoding"] = encoding
            loader = TextLoader(str(file_path), **kwargs)
            try:
                documents = loader.load()
            except Exception as exc:
                raise IngestionError(f"Failed to read {file_path.name}: {exc}") from exc
            if encoding:
                for doc in documents:
                    doc.metadata.setdefault("encoding", encoding)
            return documents

        if suffix in PDF_SUFFIXES:
            self._ensure_chardet()
            if UnstructuredPDFLoader is None:
                raise MissingDependencyError(
                    "PDF ingestion requires langchain-community unstructured loaders. "
                    "Install them via `pip install -r requirements.txt`."
                )
            self._ensure_dependency(
                "pdfminer",
                "PDF ingestion requires `pdfminer.six`. Install it via `pip install pdfminer.six` "
                "or `pip install unstructured[local-inference]`.",
            )
            loader = UnstructuredPDFLoader(str(file_path))
            try:
                documents = loader.load()
            except Exception as exc:
                self._handle_loader_failure(
                    file_path,
                    exc,
                    "Install `unstructured[local-inference]` to enable PDF ingestion.",
                    "Failed to parse PDF",
                )
            encoding = self._detect_encoding(file_path)
            if encoding:
                for doc in documents:
                    doc.metadata.setdefault("encoding", encoding)
            return documents

        if suffix in EXCEL_SUFFIXES:
            self._ensure_chardet()
            if UnstructuredExcelLoader is None:
                raise MissingDependencyError(
                    "XLSX ingestion requires langchain-community Excel loaders. "
                    "Install them via `pip install -r requirements.txt`."
                )
            self._ensure_dependency(
                "openpyxl",
                "XLSX ingestion requires `openpyxl`. Install it via `pip install openpyxl`.",
            )
            loader = UnstructuredExcelLoader(str(file_path))
            try:
                documents = loader.load()
            except Exception as exc:
                self._handle_loader_failure(
                    file_path,
                    exc,
                    "Install `unstructured[local-inference]` and `openpyxl` to enable spreadsheet ingestion.",
                    "Failed to parse spreadsheet",
                )
            encoding = self._detect_encoding(file_path)
            if encoding:
                for doc in documents:
                    doc.metadata.setdefault("encoding", encoding)
            return documents

        raise IngestionError(
            f"Unsupported file type '{suffix or 'unknown'}' for {file_path.name}. "
            "Supported extensions include Markdown, text, PDF, and XLSX."
        )

    def _load_documents(self, path: Path) -> List:
        if path.is_file():
            return self._load_file_documents(path)

        documents: List = []
        errors: List[str] = []
        for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
            try:
                docs = self._load_file_documents(file_path)
            except MissingDependencyError as exc:
                errors.append(f"{file_path.name}: {exc}")
                continue
            except IngestionError as exc:
                errors.append(f"{file_path.name}: {exc}")
                continue

            documents.extend(docs)

        if documents:
            for warning in errors:
                self._logger.warning("⚠️  Skipped %s", warning)
            return documents

        if errors:
            raise IngestionError("; ".join(errors))

        return documents

    def _search_memory(self, coll_name: str, question: str) -> Tuple[str, List[str]]:
        if coll_name not in utility.list_collections():
            return "(No local results found.)", []

        collection = Collection(coll_name)
        collection.load()
        query_vec = self.embeddings.embed_query(question)
        results = collection.search(
            data=[query_vec],
            anns_field="embedding",
            param={"metric_type": "IP"},
            limit=4,
            output_fields=["text", "source"],
        )

        if not results or not results[0]:
            return "(No local results found.)", []

        chunks = []
        citations = []
        for hit in results[0]:
            text = hit.entity.get("text", "")
            source = hit.entity.get("source", "")
            chunks.append(text if not source else f"{text}\n(Source: {source})")
            if source:
                citations.append(source)
        return "\n\n".join(chunks), citations

    def _synthesise_answer(self, question: str, context: str) -> str:
        prompt = (
            "You are Yo, a helpful local research assistant. "
            "Answer using only the supplied context. "
            "If the context is empty, say you do not have enough information.\n\n"
            f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
        )
        response = self.client.generate(model=self.model_name, prompt=prompt)
        return response["response"]

    def _prepare_chat(
        self,
        message: str,
        namespace: str,
        history: list[dict[str, str]] | None,
        web: bool,
    ) -> tuple[list[dict[str, str]], str, list[str]]:
        coll_name = self._collection_name(namespace)
        memory_context, citations = self._search_memory(coll_name, message)

        system_prompt = (
            "You are Yo, a concise local research assistant. "
            "Use the provided context and prior conversation to answer. "
            "If the context does not contain the answer, acknowledge the gap honestly."
        )
        if memory_context:
            system_prompt += f"\n\nContext:\n{memory_context}"
        if web:
            system_prompt += "\n\nWeb augmentation may have been applied; cite sources when possible."

        conversation: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if history:
            for turn in history[-10:]:
                user_msg = turn.get("user")
                assistant_msg = turn.get("assistant")
                if user_msg:
                    conversation.append({"role": "user", "content": str(user_msg)})
                if assistant_msg:
                    conversation.append({"role": "assistant", "content": str(assistant_msg)})

        conversation.append({"role": "user", "content": message})
        return conversation, memory_context, citations

    def chat(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: list[dict[str, str]] | None = None,
        web: bool = False,
    ) -> dict[str, Any]:
        """Return a conversational reply using optional prior history."""

        if not message:
            raise ValueError("Message cannot be empty.")

        namespace = namespace or self.active_namespace
        conversation, memory_context, citations = self._prepare_chat(message, namespace, history, web)

        response = self.client.chat(model=self.model_name, messages=conversation)
        reply = ""
        if isinstance(response, dict):
            message_block = response.get("message")
            if isinstance(message_block, dict):
                reply = message_block.get("content") or ""
            reply = reply or response.get("response", "")
        reply = reply or "(No response generated.)"

        payload: dict[str, Any] = {
            "response": reply.strip(),
            "context": memory_context,
            "citations": citations,
        }
        return payload

    def chat_stream(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: list[dict[str, str]] | None = None,
        web: bool = False,
    ):
        """Yield chat tokens followed by a completion payload."""

        if not message:
            raise ValueError("Message cannot be empty.")

        namespace = namespace or self.active_namespace
        conversation, memory_context, citations = self._prepare_chat(message, namespace, history, web)

        collected: list[str] = []
        stream = self.client.chat(model=self.model_name, messages=conversation, stream=True)
        for chunk in stream:
            token = ""
            if isinstance(chunk, dict):
                message_block = chunk.get("message")
                if isinstance(message_block, dict):
                    token = message_block.get("content") or ""
                token = token or chunk.get("response", "")
            if token:
                collected.append(token)
                yield {"token": token, "done": False}

        reply = "".join(collected).strip()
        yield {
            "token": "",
            "done": True,
            "response": reply,
            "context": memory_context,
            "citations": citations,
        }
