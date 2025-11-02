"""
yo.memory — Persistent recall manager using Milvus Lite.
Handles namespaces, collections, and embeddings for document recall.
"""
from pymilvus import connections

class YoMemory:
    def __init__(self, uri="data/milvus_lite.db"):
        connections.connect(alias="default", uri=uri)
        print(f"✅ Connected to Milvus Lite memory: {uri}")

