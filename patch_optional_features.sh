#!/bin/bash
# ============================================
# Yo Optional Features Patch
# Auto-index verification + namespace commands
# ============================================

echo "🔧 Adding auto-index verification + namespace management..."

cat > yo/brain.py <<'EOF'
# -*- coding: utf-8 -*-
"""
yo.brain — adds auto-index creation and namespace list/delete commands
"""
from pathlib import Path
from pymilvus import (
    connections,
    Collection,
    list_collections,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility
)
from ollama import Client
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import requests, re, json, os
from datetime import datetime

OLLAMA_MODEL = "llama3"
EMBED_MODEL = "nomic-embed-text"
CACHE_PATH = Path("data/web_cache.json")

class YoBrain:
    def __init__(self, data_dir="data/milvus_lite.db"):
        self.client = Client()
        self.data_dir = Path(data_dir)
        connections.connect(alias="default", uri=str(data_dir))

    # ---------- Index Verification ----------
    def ensure_index(self, namespace):
        coll_name = f"yo_{namespace}"
        if coll_name not in list_collections():
            print(f"⚠️ Namespace '{namespace}' not found.")
            return
        col = Collection(coll_name)
        index_info = col.indexes
        if not index_info:
            print(f"🔨 Creating index for '{coll_name}' ...")
            col.create_index(
                field_name="embedding",
                index_params={
                    "index_type": "IVF_FLAT",
                    "metric_type": "L2",
                    "params": {"nlist": 128}
                }
            )
            col.load()
            print(f"✅ Index built for '{coll_name}'")
        else:
            print(f"✅ Index already exists for '{coll_name}'")

    # ---------- Namespace Management ----------
    def ns_list(self):
        namespaces = [c.replace("yo_", "") for c in list_collections()]
        if not namespaces:
            print("ℹ️ No namespaces found.")
            return
        print("🧭 Namespaces:")
        for n in namespaces:
            print(f" - {n}")

    def ns_delete(self, namespace):
        coll_name = f"yo_{namespace}"
        if coll_name not in list_collections():
            print(f"⚠️ Namespace '{namespace}' not found.")
            return
        confirm = input(f"⚠️ Delete namespace '{namespace}'? [y/N]: ").lower()
        if confirm == "y":
            utility.drop_collection(coll_name)
            print(f"🗑️ Namespace '{namespace}' deleted.")
        else:
            print("❎ Delete cancelled.")

    # ---------- Embeddings ----------
    def embed(self, text):
        emb = self.client.embeddings(model=EMBED_MODEL, prompt=text)
        return emb["embedding"]

    # ---------- Ingest ----------
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
        print(f"✅ Ingestion complete for '{namespace}'")
        self.ensure_index(namespace)

    # ---------- Ask ----------
    def ask(self, question, namespace="default", web=False, top_k=3):
        coll_name = f"yo_{namespace}"
        if coll_name not in list_collections():
            print(f"⚠️ Namespace '{namespace}' not found.")
            return
        self.ensure_index(namespace)
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
        context = "\n\n".join([hit.entity.get("text") for hit in results[0]])

        if web:
            print("🌐 Fetching live web context...")
            url = f"https://duckduckgo.com/html/?q={requests.utils.quote(question)}"
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            snippets = re.findall(r'<a rel="nofollow" class="result__a".*?>(.*?)</a>', r.text)
            web_context = "\n".join(re.sub(r"<.*?>", "", s) for s in snippets[:3])
            context += f"\n\n[Web Results]\n{web_context}"

        print("🧠 Generating answer...")
        resp = self.client.generate(model=OLLAMA_MODEL,
            prompt=f"Using the following context, answer the question:\n\n{context}\n\nQuestion: {question}")
        print("\n💬 Yo says:\n")
        print(resp["response"])

    # ---------- Summarize ----------
    def summarize(self, namespace="default"):
        coll_name = f"yo_{namespace}"
        if coll_name not in list_collections():
            print(f"⚠️ Namespace '{namespace}' not found.")
            return
        col = Collection(coll_name)
        col.load()
        results = col.query(expr="", output_fields=["text"], limit=100)
        text = "\n".join(r["text"] for r in results)
        print("🧠 Summarizing...")
        resp = self.client.generate(model=OLLAMA_MODEL,
            prompt=f"Summarize the following knowledge base:\n\n{text[:8000]}")
        print("\n📘 Summary:\n")
        print(resp["response"])
EOF

# CLI update
cat > yo/cli.py <<'EOF'
"""
yo.cli — includes namespace commands
"""
import argparse
from yo.brain import YoBrain

def main():
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    parser.add_argument("command", choices=["add","ask","summarize","ns"])
    parser.add_argument("arg", nargs="?", default=None)
    parser.add_argument("--ns", default="default")
    parser.add_argument("--web", action="store_true")
    args = parser.parse_args()

    brain = YoBrain()

    if args.command == "add":
        brain.ingest(args.arg, namespace=args.ns)
    elif args.command == "ask":
        brain.ask(args.arg, namespace=args.ns, web=args.web)
    elif args.command == "summarize":
        brain.summarize(namespace=args.ns)
    elif args.command == "ns":
        if args.arg == "list":
            brain.ns_list()
        elif args.arg == "delete":
            brain.ns_delete(args.ns)
        else:
            print("Usage:\n  yo ns list\n  yo ns delete --ns <name>")

if __name__ == "__main__":
    main()
EOF

echo "✅ Optional features added!"
echo "Try:"
echo "  python3 -m yo.cli ns list"
echo "  python3 -m yo.cli ns delete --ns default"
echo "  python3 -m yo.cli add ./docs/ --ns test"
