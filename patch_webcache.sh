#!/bin/bash
# =======================================
# Yo Web Cache Patch Script
# Adds local caching for web search results
# =======================================

echo "🔧 Patching Yo for web cache support..."

cat > yo/brain.py <<'EOF'
# -*- coding: utf-8 -*-
"""
yo.brain — Web-aware retrieval with caching support.
"""
from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from pymilvus import connections, Collection, list_collections
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

    # ---- Web cache helpers ----
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
        cache[query] = {
            "timestamp": datetime.now().isoformat(),
            "results": results
        }
        self._save_cache(cache)

    # ---- Embeddings ----
    def embed(self, text):
        emb = self.client.embeddings(model=EMBED_MODEL, prompt=text)
        return emb["embedding"]

    # ---- Ask with optional web ----
    def ask(self, question, namespace="default", web=False, top_k=3):
        coll_name = f"yo_{namespace}"
        context_parts = []

        # Step 1: Local retrieval
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

        # Step 2: Optional web context (with caching)
        if web:
            cached = self._get_cached_web_results(question)
            if cached:
                print("💾 Using cached web context...")
                text_snippets = cached
            else:
                print("🌐 Fetching live web context...")
                try:
                    search_url = f"https://duckduckgo.com/html/?q={requests.utils.quote(question)}"
                    r = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"})
                    snippets = re.findall(r'<a rel="nofollow" class="result__a".*?>(.*?)</a>', r.text)
                    text_snippets = [re.sub(r"<.*?>", "", s) for s in snippets[:3]]
                    self._store_web_results(question, text_snippets)
                except Exception as e:
                    text_snippets = [f"Error fetching web data: {e}"]
            web_context = "\n".join(text_snippets)
            context_parts.append(f"[Web Results]\n{web_context}")

        # Step 3: Combine and generate
        combined_context = "\n\n".join(context_parts)
        print("\n📚 Context Used:\n")
        print(combined_context)
        print("\n🧠 Generating final answer...\n")

        prompt = f"Using the following context, answer the question:\n\n{combined_context}\n\nQuestion: {question}"
        resp = self.client.generate(model=OLLAMA_MODEL, prompt=prompt)
        print("💬 Yo says:\n")
        print(resp["response"])
EOF

echo "✅ Web caching patch applied!"
echo "You can test with:"
echo "    python3 -m yo.cli ask 'What is LangChain?' --web"
echo "Re-run the same query twice to see caching in action (💾 message)."

