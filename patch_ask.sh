#!/bin/bash
# =========================================
# Yo Retrieval + Ask Feature Patch Script
# =========================================

echo "🔧 Patching yo/brain.py with retrieval + ask method..."
cat > yo/brain.py <<'EOF'
# -*- coding: utf-8 -*-
"""
yo.brain — now includes retrieval-based Q&A (ask)
"""
from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, list_collections
from ollama import Client
import numpy as np

OLLAMA_MODEL = "llama3"
EMBED_MODEL = "nomic-embed-text"

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

    def embed(self, text):
        """Generate a vector embedding for text."""
        emb = self.client.embeddings(model=EMBED_MODEL, prompt=text)
        return np.array(emb["embedding"], dtype=np.float32)

    def ingest(self, folder, namespace="default"):
        print(f"📂 Ingesting from '{folder}' into namespace '{namespace}' ...")
        docs = self.load_docs(folder)
        coll_name = f"yo_{namespace}"
        existing = list_collections()
        if coll_name not in existing:
            print(f"🪣 Creating new Milvus collection '{coll_name}'")
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=4096),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=768),
            ]
            schema = CollectionSchema(fields)
            Collection(name=coll_name, schema=schema)
        else:
            print(f"✅ Using existing namespace '{coll_name}'")
        col = Collection(coll_name)
        for d in docs:
            emb = self.embed(d.page_content)
            col.insert([[None], [d.page_content], [emb.tolist()]])
            print(f"📄 {d.metadata.get('source')} indexed.")

    def ask(self, question, namespace="default", top_k=3):
        """Retrieve relevant chunks and answer using Ollama."""
        coll_name = f"yo_{namespace}"
        if coll_name not in list_collections():
            print(f"⚠️ Namespace '{namespace}' not found. Run ingestion first.")
            return
        col = Collection(coll_name)
        q_emb = self.embed(question)
        col.load()
        results = col.search(
            data=[q_emb.tolist()],
            anns_field="embedding",
            param={"metric_type": "L2"},
            limit=top_k,
            output_fields=["text"],
        )
        context = "\n\n".join([hit.entity.get("text") for hit in results[0]])
        prompt = f"Using the following context, answer the question:\n\n{context}\n\nQuestion: {question}"
        resp = self.client.generate(model=OLLAMA_MODEL, prompt=prompt)
        print("\n🧠 Yo says:\n")
        print(resp["response"])
EOF

echo "🔧 Patching yo/cli.py to wire up ask()..."
cat > yo/cli.py <<'EOF'
"""
yo.cli — now supports `yo ask "question"`
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
        print("🧠 Summarization placeholder — coming soon!")

if __name__ == "__main__":
    main()
EOF

echo "✅ Patch complete! Try it out:"
echo "    python3 -m yo.cli ask 'What is Ollama?'"

