🧠 YO RAG PIPELINE — USER GUIDE
🚀 Overview

Yo RAG is a local Retrieval-Augmented Generation (RAG) pipeline built around

Milvus Lite (embedded vector database)

LangChain (retrieval & orchestration)

Ollama (LLMs + embeddings)

It lets you ingest local text files and query them conversationally — all offline.

🧩 Key Features
Feature	Description
Local Milvus Lite	Stores vector embeddings in a lightweight .db file—no external server.
Ollama Integration	Uses local Ollama models for both embeddings and generation.
LangChain Framework	Provides retrieval, prompt-templating, and chain management.
Fully Offline	No external API keys or network calls required.
Persistent Data	Keeps your vectors in data/milvus_lite.db between runs.
⚙️ Installation
1️⃣ Prerequisites

Python ≥ 3.10

Ollama installed and running
👉 https://ollama.com/download

2️⃣ Clone the Repository
git clone https://github.com/SeansGravy/yo-rag.git
cd yo-rag

3️⃣ Install Dependencies
pip install -U langchain langchain-core langchain-text-splitters langchain-milvus langchain-ollama pymilvus ollama

4️⃣ Pull Required Ollama Models
ollama pull nomic-embed-text   # for embeddings
ollama pull llama3             # or your preferred LLM

🏗️ Project Structure
yo-rag/
├── rag/
│   └── pipeline.py        # main RAG pipeline
├── docs/                  # your source documents
├── data/                  # local Milvus Lite DB
└── USER_GUIDE.md          # this file

🧠 Usage
🪣 Ingest Documents

Add one or more .txt or .md files to docs/, then run:

python3 -m rag.pipeline --ingest ./docs/


✅ Expected output:

🗄️  Using Milvus Lite at /path/to/data/milvus_lite.db
✅ Connected to Milvus Lite
Ingesting 3 chunks from ./docs/…
✅ Ingestion complete.

💬 Ask Questions

Query your knowledge base:

python3 -m rag.pipeline --ask "What is LangChain used for?"


🧠 Example response:

LangChain helps developers build applications that combine large language models with external data and tools.

🔁 Combine Both

You can chain ingestion and query in one line:

python3 -m rag.pipeline --ingest ./docs/ --ask "Summarize my documents"

🧩 Example Workflow
mkdir docs
echo "LangChain connects LLMs to data and tools." > docs/langchain.txt
python3 -m rag.pipeline --ingest ./docs/
python3 -m rag.pipeline --ask "What does LangChain do?"

⚡ Troubleshooting
Problem	Cause	Fix
404 model not found	The embedding model isn’t downloaded.	Run ollama pull nomic-embed-text.
Fail connecting to server on localhost:19530	Milvus defaulted to server mode.	Ensure pipeline.py uses langchain-milvus and a local .db URI.
No .txt files found	Docs folder empty.	Add .txt or .md files to ./docs/.
Slow responses	Large docs or small model	Try smaller docs or a faster Ollama model (mistral, phi3, etc.).
🧭 Future Enhancements

Web UI (FastAPI or Gradio)

Automatic summarization after ingestion

Metadata tagging (per-file topics)

Periodic re-ingestion script

Multi-collection support in Milvus

🪪 Version Info
Component	Version
Python	≥ 3.10
LangChain	0.3+
LangChain-Milvus	latest
Ollama	current local
Milvus Lite	Embedded via pymilvus
🤝 Credits

Built by Sean & Logos, 2025
With guidance from LangChain, Milvus, and Ollama open-source communities.
