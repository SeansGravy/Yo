# -*- coding: utf-8 -*-
"""
yo.brain — complete working class for Yo 0.2.0
"""
from pathlib import Path
from pymilvus import connections, Collection, list_collections, CollectionSchema, FieldSchema, DataType
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from ollama import Client
import requests, re, json
from datetime import datetime

OLLAMA_MODEL = "llama3"
EMBED_MODEL = "nomic-embed-text"
CACHE_PATH = Path("data/web_cache.json")

class YoBrain:
    def __init__(self, data_dir="data/milvus_lite.db"):
        self.client = Client()
        self.data_dir = Path(data_dir)
        connections.connect(alias="default", uri=str(data_dir))

    # ---- Cache helpers ----
    def _load_cache(self):
        if CACHE_PATH.exists():
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_cache(self, cache):
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)

    def _get_cached_web_results(self, query, max_age_hours=24):
        cache = self._load_cache()
        if query in cache:
            ts = datetime.fromisoformat(cache[query]["timestamp"])
            if (datetime.now() - ts).total_seconds() < max_age_hours * 3600:
                return cache[query]["results"]
        return None

    def _store_web_results(self, query, results):
        cache = self._load_cache()
        cache[query] = {"timestamp": datetime.now().isoformat(), "results": results}
        self._save_cache(cache)

    def _clear_cache(self):
        if CACHE_PATH.exists():
            CACHE_PATH.unlink()
            print("🧹 Cache cleared.")
        else:
            print("ℹ️ No cache found to clear.")

    def _list_cache(self):
        cache = self._load_cache()
        if not cache:
            print("ℹ️ No cached queries yet.")
            return
        print("🧾 Cached queries:")
        for q, data in cache.items():
            print(f" - {q} (cached {data['timestamp']})")

    # ---- Embedding ----
    def embed(self, text):
        emb = self.client.embeddings(model=EMBED_MODEL, prompt=text)
        return emb["embedding"]

    # ---- Ingest ----
    def ingest(self, folder, namespace="default"):
        print(f"📂 Ingesting from '{folder}' into namespace '{namespace}' ...")
        loader = DirectoryLoader(folder, glob="**/*.txt", loader_cls=TextLoader)
        docs = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
        chunks = splitter.split_documents(docs)

        coll_name = f"yo_{namespace}"
        if coll_name not in list_collections():
            print(f"🪣 Creating new Milvus collection '{coll_name}'")
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=4096),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=768),
            ]
            schema = CollectionSchema(fields)
            Collection(name=coll_name, schema=schema)

        col = Collection(coll_name)
        for d in chunks:
            emb = self.embed(d.page_content)
            col.insert([[d.page_content], [emb]])
            print(f"📄 Indexed: {d.metadata.get('source')}")
        print(f"✅ Ingestion complete for namespace '{namespace}'.")

    # ---- Ask ----
    def ask(self, question, namespace="default", web=False, top_k=3):
        coll_name = f"yo_{namespace}"
        context_parts = []

        # Memory retrieval
        if coll_name in list_collections():
            col = Collection(coll_name)
            q_emb = self.embed(question)
            col.load()
            results = col.search(
                data=[q_emb],
                anns_field="embedding",
                param={"metric_type": "L2"},
                limit=top_k,
                output_fields=["text"],
            )
            memory_context = "\n\n".join([hit.entity.get("text") for hit in results[0]])
            context_parts.append(f"[Memory Results]\n{memory_context}")
        else:
            context_parts.append("[Memory Results]\n(No local results found.)")

        # Optional web context
        if web:
            cached = self._get_cached_web_results(question)
            if cached:
                print("💾 Using cached web context...")
                snippets = cached
            else:
                print("🌐 Fetching live web context...")
                try:
                    url = f"https://duckduckgo.com/html/?q={requests.utils.quote(question)}"
                    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    raw_snips = re.findall(r'<a rel="nofollow" class="result__a".*?>(.*?)</a>', r.text)
                    snippets = [re.sub(r"<.*?>", "", s) for s in raw_snips[:3]]
                    self._store_web_results(question, snippets)
                except Exception as e:
                    snippets = [f"Error fetching web data: {e}"]
            web_context = "\n".join(snippets)
            context_parts.append(f"[Web Results]\n{web_context}")

        # Generate final
        combined = "\n\n".join(context_parts)
        print("\n📚 Context Used:\n")
        print(combined)
        print("\n🧠 Generating final answer...\n")
        prompt = f"Using the following context, answer the question:\n\n{combined}\n\nQuestion: {question}"
        resp = self.client.generate(model=OLLAMA_MODEL, prompt=prompt)
        print("💬 Yo says:\n")
        print(resp["response"])

    # ---- Summarize ----
    def summarize(self, namespace="default"):
        coll_name = f"yo_{namespace}"
        if coll_name not in list_collections():
            print(f"Namespace '{namespace}' not found. Run ingestion first.")
            return
        col = Collection(coll_name)
        col.load()
        results = col.query(expr="", output_fields=["text"], limit=100)
        all_text = "\n".join(r["text"] for r in results)
        print("🧠 Generating summary...")
        resp = self.client.generate(model=OLLAMA_MODEL,
            prompt=f"Summarize the following knowledge base:\n\n{all_text[:8000]}")
        print("\n📘 Summary:\n")
        print(resp["response"])
