#!/bin/bash
# =======================================
# Yo Web-Aware Retrieval (--web flag)
# =======================================

echo "🔧 Adding web-aware retrieval feature to Yo..."

# --- Update yo/brain.py ---
cat > yo/brain.py <<'EOF'
# -*- coding: utf-8 -*-
"""
yo.brain — now supports web-aware retrieval with DuckDuckGo search.
"""
from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from pymilvus import connections, Collection, list_collections
from ollama import Client
import requests
import re

OLLAMA_MODEL = "llama3"
EMBED_MODEL = "nomic-embed-text"

class YoBrain:
    def __init__(self, data_dir="data/milvus_lite.db"):
        self.client = Client()
        self.data_dir = Path(data_dir)
        connections.connect(alias="default", uri=str(data_dir))

    def embed(self, text):
        emb = self.client.embeddings(model=EMBED_MODEL, prompt=text)
        return emb["embedding"]

    def ask(self, question, namespace="default", web=False, top_k=3):
        coll_name = f"yo_{namespace}"
        context_parts = []

        # Step 1: Pull from Milvus (if namespace exists)
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

        # Step 2: Optional web search
        if web:
            print("🌐 Fetching live web context...")
            try:
                search_url = f"https://duckduckgo.com/html/?q={requests.utils.quote(question)}"
                r = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"})
                snippets = re.findall(r'<a rel="nofollow" class="result__a".*?>(.*?)</a>', r.text)
                text_snippets = [re.sub(r"<.*?>", "", s) for s in snippets[:3]]
                web_context = "\n".join(text_snippets)
                context_parts.append(f"[Web Results]\n{web_context}")
            except Exception as e:
                context_parts.append(f"[Web Results]\nError fetching web data: {e}")

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

# --- Update yo/cli.py ---
cat > yo/cli.py <<'EOF'
"""
yo.cli — adds --web flag for live retrieval
"""
import argparse
from yo.brain import YoBrain

def main():
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    parser.add_argument("command", choices=["add", "ask", "summarize"])
    parser.add_argument("arg", nargs="?", default=None, help="Path or question")
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

if __name__ == "__main__":
    main()
EOF

echo "✅ Patch complete. Test with:"
echo "    python3 -m yo.cli ask 'What's new in LangChain 0.3?' --web"

