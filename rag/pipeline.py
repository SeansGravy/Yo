"""
Yo RAG Pipeline — Updated to use langchain-milvus (Milvus Lite compatible)
"""

from pathlib import Path
from langchain_community.llms import Ollama
from langchain_community.embeddings import OllamaEmbeddings
from langchain_milvus import Milvus  # ✅ new package supports Lite
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_classic.chains.retrieval import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import PromptTemplate
from pymilvus import connections


class YoRAG:
    def __init__(
        self,
        collection_name="yo_docs",
        model_name="llama3",
        embed_model="nomic-embed-text",
    ):
        base = Path(__file__).resolve().parent.parent
        data_dir = base / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "milvus_lite.db"

        print(f"🗄️  Using Milvus Lite at {db_path}")
        connections.connect(alias="default", uri=str(db_path))
        print("✅ Connected to Milvus Lite")

        self.connection_args = {"uri": str(db_path)}  # supported by langchain-milvus
        self.embeddings = OllamaEmbeddings(model=embed_model)
        self.llm = Ollama(model=model_name)
        self.collection_name = collection_name

    def ingest(self, path: str):
        """Chunk, embed, and insert docs into Milvus Lite."""
        loader = DirectoryLoader(path, glob="**/*.txt", loader_cls=TextLoader)
        docs = loader.load()
        if not docs:
            print(f"⚠️  No .txt files found in {path}")
            return

        splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        print(f"Ingesting {len(chunks)} chunks from {path}…")

        Milvus.from_documents(
            chunks,
            self.embeddings,
            collection_name=self.collection_name,
            connection_args=self.connection_args,
        )
        print("✅ Ingestion complete.")

    def query(self, question: str, k: int = 5):
        """Retrieve relevant chunks and generate grounded answer."""
        vectorstore = Milvus(
            self.embeddings,
            collection_name=self.collection_name,
            connection_args=self.connection_args,
        )
        retriever = vectorstore.as_retriever(search_kwargs={"k": k})

        prompt = PromptTemplate.from_template(
            "Use the following context to answer the question.\n\n"
            "Context:\n{context}\n\nQuestion:\n{input}"
        )

        qa_chain = create_stuff_documents_chain(self.llm, prompt)
        chain = create_retrieval_chain(retriever, qa_chain)
        result = chain.invoke({"input": question})
        answer = result.get("answer") or result.get("output") or "No answer generated."
        return answer, []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Yo RAG CLI (Milvus Lite Updated)")
    parser.add_argument("--ingest", type=str, help="Path to folder of .txt docs")
    parser.add_argument("--ask", type=str, help="Question to ask")
    args = parser.parse_args()

    rag = YoRAG()

    if args.ingest:
        rag.ingest(args.ingest)
    if args.ask:
        answer, _ = rag.query(args.ask)
        print("\n🧠 Yo says:\n", answer)
