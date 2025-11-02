---

# 🧠 Yo RAG Pipeline

A **local Retrieval-Augmented Generation (RAG)** system powered by
**Milvus Lite**, **LangChain**, and **Ollama** — everything runs offline.

---

## 🚀 Quick Start

```bash
git clone https://github.com/SeansGravy/Yo.git
cd Yo
pip install -U langchain langchain-milvus langchain-ollama pymilvus ollama
ollama pull nomic-embed-text   # embeddings
ollama pull llama3             # or your preferred LLM
```

### Ingest & Query

```bash
python3 -m rag.pipeline --ingest ./docs/
python3 -m rag.pipeline --ask "What is LangChain used for?"
```

✅ **Output**

```
🗄️  Using Milvus Lite at ./data/milvus_lite.db
✅ Connected to Milvus Lite
✅ Ingestion complete.
🧠 Yo says:
LangChain helps developers connect LLMs to external data and tools.
```

---

## 📂 Project Layout

```
Yo/
├── rag/
│   └── pipeline.py      # main RAG pipeline
├── docs/                # your source files
├── data/                # Milvus Lite .db
└── USER_GUIDE.md        # full documentation
```

---

## 🧩 Tech Stack

| Component         | Role                               |
| ----------------- | ---------------------------------- |
| **Milvus Lite**   | Vector store (embedded, no server) |
| **LangChain**     | Retrieval orchestration            |
| **Ollama**        | Local LLM + embeddings             |
| **Python ≥ 3.10** | Runtime                            |

---

## 🛠️ Next Steps

* Add more documents under `./docs/`
* Try different Ollama models (`mistral`, `phi3`, etc.)
* Build a small FastAPI/Gradio UI

---

### 🤝 Credits

Built by **Sean & Logos**, 2025
Inspired by LangChain, Milvus, and Ollama open-source communities.

---
