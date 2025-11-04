"""Core Yo brain logic.

This module provides the main orchestration layer for the Yo CLI.  It handles
Milvus Lite lifecycle management, document ingestion, retrieval, summarisation,
and simple web-context caching for the optional web-aware mode.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timedelta
from importlib import util as import_util
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, NoReturn

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
        data_dir: Path | str = "data",
        model_name: str = "llama3",
        embed_model: str = "nomic-embed-text",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "milvus_lite.db"
        self.recover_dir = self.data_dir / "recoveries"
        self.recover_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.data_dir / "web_cache.json"
        self.meta_path = self.data_dir / "namespace_meta.json"

        self.model_name = model_name
        self.embed_model = embed_model

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

        self.client = Client()  # type: ignore[operator]
        self.embeddings = OllamaEmbeddings(model=self.embed_model)  # type: ignore[operator]

        self._connect_milvus()

    # ------------------------------------------------------------------
    # Milvus helpers
    # ------------------------------------------------------------------
    def _connect_milvus(self) -> None:
        """Connect to Milvus Lite, handling locked database recovery."""

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
            print("⚠️  Cache file was corrupted. Resetting web cache.")
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
        entry["last_ingested"] = datetime.now().isoformat()
        if documents is not None:
            existing = int(entry.get("documents", 0) or 0)
            entry["documents"] = existing + int(documents)
        if chunks is not None:
            existing_chunks = int(entry.get("chunks", 0) or 0)
            entry["chunks"] = existing_chunks + int(chunks)
        self._save_namespace_meta(meta)

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
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Source path not found: {source}")

        documents = self._load_documents(path)
        if not documents:
            print(f"⚠️  No ingestible documents found under {source}.")
            return

        splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=120)
        chunks = splitter.split_documents(documents)
        print(f"🧩 Created {len(chunks)} chunks for namespace '{namespace}'.")

        collection = self._ensure_collection(namespace)

        payloads = [chunk.page_content for chunk in chunks]
        sources = [str(chunk.metadata.get("source", "")) for chunk in chunks]
        embeddings = self.embeddings.embed_documents(payloads)

        base_id = int(time.time() * 1000)
        ids = [base_id + idx for idx in range(len(chunks))]

        collection.insert([ids, payloads, sources, embeddings])
        collection.flush()
        print("✅ Ingestion complete.")
        summary = {
            "namespace": namespace,
            "documents_ingested": len(documents),
            "chunks_ingested": len(chunks),
        }
        self._update_namespace_meta(
            namespace,
            documents=len(documents),
            chunks=len(chunks),
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

        if sorted_names:
            print("🗂️  Available namespaces:")
            for ns in sorted_names:
                print(f" - {ns}")
        else:
            print("(no namespaces found)")

        return sorted_names

    def namespace_activity(self) -> Dict[str, Dict[str, Any]]:
        meta = self._load_namespace_meta()
        activity: Dict[str, Dict[str, Any]] = {}
        for ns in self.ns_list(silent=True):
            entry = meta.get(ns, {})
            stats: Dict[str, Any] = {
                "last_ingested": entry.get("last_ingested"),
                "documents": entry.get("documents"),
                "chunks": entry.get("chunks"),
            }
            stats.update(self._namespace_stats(ns))
            activity[ns] = stats
        return activity

    def ns_delete(self, namespace: str) -> None:
        coll_name = self._collection_name(namespace)
        if coll_name not in utility.list_collections():
            raise ValueError(f"Namespace '{namespace}' does not exist.")
        utility.drop_collection(coll_name)
        print(f"🗑️  Deleted namespace '{namespace}'.")
        meta = self._load_namespace_meta()
        if meta.pop(namespace, None) is not None:
            self._save_namespace_meta(meta)

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
                print(f"⚠️  Skipped {warning}")
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

