#!/bin/bash
set -euo pipefail

echo "🔧 Updating Yo documentation…"
mkdir -p docs

# -----------------------------
# README.md (concise landing)
# -----------------------------
cat > README.md <<'EOF'
# 🧠 Yo — Local RAG Assistant

**Yo** is a fully local Retrieval-Augmented Generation (RAG) stack built on:
- **Ollama** for LLM + embeddings
- **Milvus Lite** for vector storage (no external server)
- **LangChain Community** utilities for loaders & orchestration

### Features
- Local-only ingestion & retrieval (Milvus Lite `.db`)
- `yo add` to index documents into namespaces
- `yo ask` to answer questions from your knowledge base
- `--web` to blend live web snippets with memory (with cache)
- `yo summarize` to print namespace summaries
- Cache management: `yo cache list`, `yo cache clear`

### Quick Start
```bash
git clone https://github.com/SeansGravy/Yo.git
cd Yo
python3 -m venv .venv && source .venv/bin/activate
pip install -U langchain langchain-community langchain-text-splitters pymilvus ollama requests
ollama pull llama3
ollama pull nomic-embed-text
