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
from pathlib import Path
from typing import List, Tuple

import requests
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from ollama import Client
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)


EMBED_DIM = 768
CACHE_TTL = timedelta(hours=24)


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

        self.model_name = model_name
        self.embed_model = embed_model

        self.client = Client()
        self.embeddings = OllamaEmbeddings(model=self.embed_model)

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

    def _cache_fresh(self, entry: dict) -> bool:
        if not entry:
            return False
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
        except Exception:
            return False
        return datetime.now() - ts < CACHE_TTL

    def _fetch_web(self, query: str) -> List[str]:
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

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------
    def ingest(self, source: str, namespace: str = "default") -> None:
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

    def ns_list(self) -> List[str]:
        namespaces = []
        for name in utility.list_collections():
            if name.startswith("yo_"):
                namespaces.append(name[len("yo_"):])
        if namespaces:
            print("🗂️  Available namespaces:")
            for ns in sorted(namespaces):
                print(f" - {ns}")
        else:
            print("(no namespaces found)")
        return sorted(namespaces)

    def ns_delete(self, namespace: str) -> None:
        coll_name = self._collection_name(namespace)
        if coll_name not in utility.list_collections():
            raise ValueError(f"Namespace '{namespace}' does not exist.")
        utility.drop_collection(coll_name)
        print(f"🗑️  Deleted namespace '{namespace}'.")

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
    def _load_documents(self, path: Path) -> List:
        if path.is_file():
            loader = TextLoader(str(path), autodetect_encoding=True)
            return loader.load()
        loader = DirectoryLoader(
            str(path),
            glob="**/*.txt",
            loader_cls=TextLoader,
            loader_kwargs={"autodetect_encoding": True},
        )
        return loader.load()

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

