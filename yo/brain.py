# -*- coding: utf-8 -*-
"""
yo.brain — fully repaired class with ingest and summarize restored
"""
from pathlib import Path
from pymilvus import connections, Collection, list_collections, CollectionSchema, FieldSchema, DataType
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from ollama import Client

OLLAMA_MODEL = "llama3"
EMBED_MODEL = "nomic-embed-text"

class YoBrain:
    def __init__(self, data_dir="data/milvus_lite.db"):
        self.client = Client()
        self.data_dir = Path(data_dir)
        connections.connect(alias="default", uri=str(data_dir))

    # ---- Embed helper ----
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

        col = Collection(coll_name)
        for d in chunks:
            emb = self.embed(d.page_content)
            col.insert([[d.page_content], [emb]])
            print(f"📄 Indexed: {d.metadata.get('source')}")
        print(f"✅ Ingestion complete for namespace '{namespace}'.")

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
        resp = self.client.generate(
            model=OLLAMA_MODEL,
            prompt=f"Summarize the following knowledge base:\n\n{all_text[:8000]}"
        )
        print("\n📘 Summary:\n")
        print(resp["response"])
