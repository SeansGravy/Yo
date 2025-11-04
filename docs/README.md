# 🧠 Yo — Local Second Brain

**Yo** is a fully offline Retrieval-Augmented Generation (RAG) assistant that runs on your machine. It ingests local text documents, stores embeddings in **Milvus Lite**, and answers questions with an **Ollama** model. You can optionally blend in cached web snippets when you ask questions.

## 🚀 Quick Start

```bash
git clone https://github.com/SeansGravy/Yo.git
cd Yo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # installs langchain-ollama>=0.1.0, milvus-lite>=2.4.4, setuptools>=81
ollama pull llama3             # generation model
ollama pull nomic-embed-text   # embedding model
# Optional (macOS/Homebrew): `brew install tesseract` to enable OCR for scanned PDFs.
```

## ▶️ Use the CLI

Every workflow goes through the CLI entry point:

```bash
python3 -m yo.cli <command> [options]
```

### Ingest files

```bash
python3 scripts/generate_ingest_fixtures.py  # ensure sample PDF/XLSX fixtures exist
python3 -m yo.cli add ./docs/ --ns default
python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research
python3 -m yo.cli add fixtures/ingest/sample.xlsx --ns finance
python3 -m yo.cli add fixtures/ingest/example.py --ns code
```

* Recursively ingests supported documents (text, Markdown, PDF, XLSX, and common source files) into `yo_<namespace>`.
* PDF ingestion requires `unstructured[local-inference]`, `pdfminer.six`, and `chardet>=5.2`. Install `pytesseract` plus the Tesseract binary for OCR of scanned pages.
* XLSX ingestion requires `openpyxl` alongside `chardet>=5.2`.
* Yo now surfaces descriptive errors when dependencies are missing or a file type is unsupported so the CLI and Lite UI can continue gracefully.

### Ask a question

```bash
python3 -m yo.cli ask "What is Yo?" --ns default
python3 -m yo.cli ask "Latest LangChain updates" --ns research --web
```

* Pulls the most relevant chunks from Milvus.
* `--web` mixes in cached DuckDuckGo snippets (24h TTL) for broader awareness.

### Summarize a namespace

```bash
python3 -m yo.cli summarize --ns default
```

Generates an overview of all content stored in that namespace.

### Manage namespaces

```bash
python3 -m yo.cli --help
```

Shows the full command catalog with a short description for each subcommand.

```bash
python3 -m yo.cli ns list
python3 -m yo.cli ns delete --ns research
```

Namespaces map to Milvus collections (`yo_<name>`).

### Work with the web cache

```bash
python3 -m yo.cli cache list
python3 -m yo.cli cache clear
```

### Compact the Milvus Lite database

```bash
python3 -m yo.cli compact
```

Runs a SQLite `VACUUM` to reclaim space from `data/milvus_lite.db`. Yo also auto-compacts when the database exceeds ~100 MiB after ingestion.

### Diagnose your setup

```bash
python3 -m yo.cli doctor
```

Prints ✅/⚠️/❌ statuses for Python, langchain, langchain-ollama>=0.1.0, setuptools>=81, milvus-lite>=2.4.4, and verifies Ollama plus Milvus Lite connectivity.

### Run the full regression test

```bash
python3 -m yo.cli verify
```

Executes `yo_full_test.sh` (if present) and writes a timestamped log next to the script.
If Milvus Lite or the Ollama backend are missing, the suite now runs the
checks that remain valid and marks the skipped portions with ⚠️ entries instead
of failing outright.

## 📁 Important Paths

| Path | Description |
| ---- | ----------- |
| `data/milvus_lite.db` | Milvus Lite SQLite-backed store for embeddings |
| `data/recoveries/` | Auto-generated backups when the DB is locked |
| `data/web_cache.json` | Cached DuckDuckGo snippets (24h TTL) |
| `docs/` | Default location for source `.txt` files |

## 🛠️ Troubleshooting

* **Database locked** – Yo automatically renames the locked file into `data/recoveries/` and recreates a fresh database.
* **No documents ingested** – Ensure the path contains supported formats (`.txt`, `.md`, `.pdf`, or common source extensions). Use `--loader` to override detection if needed.
* **Web mode errors** – Failures to fetch are returned inline and cached results are reused for 24 hours.
* **Missing models or backends** – Verify `ollama pull llama3`, `ollama pull nomic-embed-text`, and that the Ollama CLI itself is installed. When Milvus Lite or Ollama are absent, `python3 -m yo.cli verify` and `yo_full_test.sh` will skip vector-store and generation checks and report the reason so you can install the missing pieces.
* **`git pull` refuses to update** – Commit or stash your local changes first (`git status` → `git add ...` → `git commit` or `git stash --include-untracked`), then rerun `git pull origin main`.
* **OCR fallback missing text** – Install Tesseract (`brew install tesseract` on macOS) so `pytesseract` can read scanned PDFs.
* **Still stuck?** – Run `python3 -m yo.cli doctor` to diagnose Python/Ollama/dependency issues automatically, including `langchain-ollama` availability and the minimum `setuptools` version.

## 🔭 Lite UI Preview

Phase 1.5 introduces the first interactive Lite UI. Launch the FastAPI app from `yo/webui.py` to explore it locally:

```bash
uvicorn yo.webui:app --reload
```

Visit [http://localhost:8000/ui](http://localhost:8000/ui) for a dashboard that now includes:

* ✅ Backend health indicators for Milvus Lite and the Ollama runtime (with detected versions).
* 📂 A namespace table showing the last-ingested timestamp plus cumulative document and chunk counts.
* 📤 A file uploader that lets you ingest new content into any namespace without leaving the browser. The UI automatically disables ingestion controls when Milvus Lite or Ollama are missing so you know what to install next.
  * Browser uploads require the optional `python-multipart` dependency, now included in `requirements.txt`. If you trimmed dependencies manually, reinstall it via `pip install python-multipart`.

Need raw data? Poll [http://localhost:8000/api/status](http://localhost:8000/api/status) for JSON that includes the namespace metrics, backend readiness, and ingestion enablement flags used by the UI.

## 📚 More Docs

See [`USER_GUIDE.md`](USER_GUIDE.md) for an in-depth walkthrough, [`ROADMAP.md`](ROADMAP.md) for the feature roadmap, and [`Yo_Handoff_Report.md`](Yo_Handoff_Report.md) for the latest project status.
