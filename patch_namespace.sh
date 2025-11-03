#!/bin/bash
# =========================================
# Yo Namespace CLI Patch Script
# =========================================

echo "🔧 Patching yo/cli.py ..."
cat > yo/cli.py <<'EOF'
"""
yo.cli — Command-line interface for Yo Brain.
Supports namespaces (--ns) for persistent collections.

Usage:
    yo add <folder> [--ns namespace]
    yo ask "<question>" [--ns namespace]
    yo summarize [--ns namespace]
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
        print(f"💡 Coming soon: Q&A within namespace '{args.ns}'.")
    elif args.command == "summarize":
        print(f"🧠 Summarizing contents of namespace '{args.ns}' (stub).")

if __name__ == "__main__":
    main()
EOF

echo "🔧 Patching yo/brain.py ..."
cat > yo/brain.py <<'EOF'
"""
yo.brain — Core ingestion and summarization engine.
Now supports namespace isolation per collection.
"""

from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType
from ollama import Client

OLLAMA_MODEL = "llama3"

class YoBrain:
    def __init__(self, data_dir="data/milvus_lite.db"):
        self.client = Client()
        self.data_dir = Path(data_dir)
        connections.connect(alias="default", uri=str(data_dir))

    def load_docs(self, folder):
        loader = DirectoryLoader(folder, glob="**/*.txt", loader_cls=TextLoader)
        docs = loader.load()
        return docs

    def summarize(self, text):
        prompt = f"Summarize this text in 3 concise bullet points:\n\n{text[:4000]}"
        resp = self.client.generate(model=OLLAMA_MODEL, prompt=prompt)
        return resp["response"]

    def ingest(self, folder, namespace="default"):
        print(f"📂 Ingesting from '{folder}' into namespace '{namespace}' ...")
        docs = self.load_docs(folder)

        # Auto-create namespace collection if needed
        coll_name = f"yo_{namespace}"
        if coll_name not in [c.name for c in Collection.list_collections()]:
            print(f"🪣 Creating new Milvus collection '{coll_name}'")
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=4096),
            ]
            schema = CollectionSchema(fields)
            Collection(name=coll_name, schema=schema)
        else:
            print(f"✅ Using existing namespace collection '{coll_name}'")

        for d in docs:
            summary = self.summarize(d.page_content)
            print(f"📄 {d.metadata.get('source')} → {summary[:200]}...")

EOF

echo "✅ Patch applied successfully! Try:"
echo "    python3 -m yo.cli add ./docs/ --ns research"

