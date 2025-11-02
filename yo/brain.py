"""
yo.brain — Core ingestion and summarization engine.
Handles multi-format file loading, metadata tagging, and summary generation.
"""

from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from ollama import Client

OLLAMA_MODEL = "llama3"

class YoBrain:
    def __init__(self, data_dir="data/milvus_lite.db"):
        self.client = Client()
        self.data_dir = Path(data_dir)

    def load_docs(self, folder):
        loader = DirectoryLoader(folder, glob="**/*.txt", loader_cls=TextLoader)
        docs = loader.load()
        return docs

    def summarize(self, text):
        prompt = f"Summarize the following text in 3 bullet points:\n\n{text[:4000]}"
        resp = self.client.generate(model=OLLAMA_MODEL, prompt=prompt)
        return resp["response"]

    def ingest(self, folder):
        docs = self.load_docs(folder)
        for d in docs:
            summary = self.summarize(d.page_content)
            print(f"📄 {d.metadata.get('source')} → {summary[:200]}...")

