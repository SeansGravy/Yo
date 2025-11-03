#!/bin/bash
# =====================================
# Yo Summarization Command Patch Script
# =====================================

echo "🔧 Adding summarization command to yo..."

# --- Update yo/brain.py ---
cat > yo/brain.py <<'EOF'
# -*- coding: utf-8 -*-
"""
yo.brain — adds summarize command to print high-level summaries
"""
from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from pymilvus import connections, Collection, list_collections
from ollama import Client

OLLAMA_MODEL = "llama3"

class YoBrain:
    def __init__(self, data_dir="data/milvus_lite.db"):
        self.client = Client()
        self.data_dir = Path(data_dir)
        connections.connect(alias="default", uri=str(data_dir))

    def summarize(self, namespace="default"):
        coll_name = f"yo_{namespace}"
        if coll_name not in list_collections():
            print(f"⚠️ Namespace '{namespace}' not found. Run ingestion first.")
            return
        col = Collection(coll_name)
        col.load()
        results = col.query(expr=None, output_fields=["text"], limit=100)
        all_text = "\n".join(r["text"] for r in results)
        print("🧠 Generating summary...")
        resp = self.client.generate(model=OLLAMA_MODEL, prompt=f"Summarize the following knowledge base:\n\n{all_text[:8000]}")
        print("\n📘 Summary:\n")
        print(resp["response"])

EOF

# --- Update yo/cli.py ---
cat > yo/cli.py <<'EOF'
"""
yo.cli — adds `yo summarize` command for namespace summaries
"""
import argparse
from yo.brain import YoBrain

def main():
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    parser.add_argument("command", choices=["add", "ask", "summarize"])
    parser.add_argument("arg", nargs="?", default=None, help="Path or question")
    parser.add_argument("--ns", default="default", help="Namespace (collection name)")
    args = parser.parse_args()

    brain = YoBrain()

    if args.command == "add":
        brain.ingest(args.arg, namespace=args.ns)
    elif args.command == "ask":
        brain.ask(args.arg, namespace=args.ns)
    elif args.command == "summarize":
        brain.summarize(namespace=args.ns)

if __name__ == "__main__":
    main()
EOF

echo "✅ Patch applied. Test with:"
echo "    python3 -m yo.cli summarize --ns default"

