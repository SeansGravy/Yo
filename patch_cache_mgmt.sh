#!/bin/bash
# =======================================
# Yo Cache Management Patch Script
# Adds `yo cache list` and `yo cache clear`
# =======================================

echo "🔧 Adding cache management commands to Yo..."

# --- Update yo/brain.py ---
cat > yo/brain.py <<'EOF'
# -*- coding: utf-8 -*-
"""
yo.brain — Web-aware retrieval + cache management (list/clear)
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

    # ---- Cache utilities ----
    def _load_cache(self):
        if CACHE_PATH.exists():
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_cache(self, cache):
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)

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

    # ---- Embeddings ----
    def embed(self, text):
        emb = self.client.embeddings(model=EMBED_MODEL, prompt=text)
        return emb["embedding"]

    # ---- Ask method ----
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

        # Step 2: Optional web search with cache
        if web:
            cache = self._load_cache()
            cached = cache.get(question)
            if cached:
                print("💾 Using cached web context...")
                text_snippets = cached["results"]
            else:
                print("🌐 Fetching live web context...")
                try:
                    search_url = f"https://duckduckgo.com/html/?q={requests.utils.quote(question)}"
                    r = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"})
                    snippets = re.findall(r'<a rel="nofollow" class="result__a".*?>(.*?)</a>', r.text)
                    text_snippets = [re.sub(r"<.*?>", "", s) for s in snippets[:3]]
                    cache[question] = {
                        "timestamp": datetime.now().isoformat(),
                        "results": text_snippets
                    }
                    self._save_cache(cache)
                except Exception as e:
                    text_snippets = [f"Error fetching web data: {e}"]
            web_context = "\n".join(text_snippets)
            context_parts.append(f"[Web Results]\n{web_context}")

        # Step 3: Combine & answer
        combined_context = "\n\n".join(context_parts)
        print("\n📚 Context Used:\n")
        print(combined_context)
        print("\n🧠 Generating final answer...\n")

        prompt = f"Using the following context, answer the question:\n\n{combined_context}\n\nQuestion: {question}"
        resp = self.client.generate(model=OLLAMA_MODEL, prompt=prompt)
        print("💬 Yo says:\n")
        print(resp["response"])
EOF

# --- Update yo/cli.py ---
cat > yo/cli.py <<'EOF'
"""
yo.cli — Adds cache list/clear commands
"""
import argparse
from yo.brain import YoBrain

def main():
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    parser.add_argument("command", choices=["add", "ask", "summarize", "cache"])
    parser.add_argument("arg", nargs="?", default=None, help="Path, question, or cache action")
    parser.add_argument("--ns", default="default", help="Namespace (collection name)")
    parser.add_argument("--web", action="store_true", help="Use live web context")
    args = parser.parse_args()

    brain = YoBrain()

    if args.command == "add":
        brain.ingest(args.arg, namespace=args.ns)
    elif args.command == "ask":
        brain.ask(args.arg, namespace=args.ns, web=args.web)
    elif args.command == "summarize":
        brain.summarize(namespace=args.ns)
    elif args.command == "cache":
        if args.arg == "list":
            brain._list_cache()
        elif args.arg == "clear":
            brain._clear_cache()
        else:
            print("Usage: yo cache [list|clear]")

if __name__ == "__main__":
    main()
EOF

echo "✅ Cache management patch applied."
echo "Try:"
echo "  python3 -m yo.cli cache list"
echo "  python3 -m yo.cli cache clear"
