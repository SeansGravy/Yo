---

# 🧠 Yo — Local Second Brain

**Yo** is a fully offline Retrieval-Augmented Generation (RAG) assistant that runs on your machine. It ingests local text documents, stores embeddings in **Milvus Lite**, and answers questions with an **Ollama** model. You can optionally blend in cached web snippets when you ask questions.

---

## 🚀 Quick Start

```bash
git clone https://github.com/SeansGravy/Yo.git
cd Yo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull llama3             # generation model
ollama pull nomic-embed-text   # embedding model
# Optional (macOS/Homebrew): `brew install tesseract` to enable OCR for scanned PDFs.
```

---

## ▶️ Use the CLI

Every workflow goes through the CLI entry point:

```bash
python3 -m yo.cli <command> [options]
```

### Ingest files

```bash
python3 -m yo.cli add ./docs/ --ns default
python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research --loader pdf
python3 -m yo.cli add fixtures/ingest/example.py --ns code --loader code
```

* Recursively ingests supported documents (text, Markdown, PDF, and source files) and stores the embeddings in `yo_<namespace>`.
* `--loader` lets you override the detection logic (`auto`, `text`, `markdown`, `pdf`, `code`). Auto-mode mixes formats safely.
* OCR is attempted automatically for scanned PDFs when `unstructured[local-inference]` and `pytesseract` are installed.

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

Checks for Python/Ollama availability, required Python packages, and Milvus Lite connectivity. Handy when something fails after pulling updates.

### Run the full regression test

```bash
python3 -m yo.cli verify
```

Executes `yo_full_test.sh` (if present) and writes a timestamped log next to the script.

---

## 📁 Important Paths

| Path | Description |
| ---- | ----------- |
| `data/milvus_lite.db` | Milvus Lite SQLite-backed store for embeddings |
| `data/recoveries/` | Auto-generated backups when the DB is locked |
| `data/web_cache.json` | Cached DuckDuckGo snippets (24h TTL) |
| `docs/` | Default location for source `.txt` files |

---

## 🛠️ Troubleshooting

* **Database locked** – Yo automatically renames the locked file into `data/recoveries/` and recreates a fresh database.
* **No documents ingested** – Ensure the path contains supported formats (`.txt`, `.md`, `.pdf`, or common source extensions). Use `--loader` to override detection if needed.
* **Web mode errors** – Failures to fetch are returned inline and cached results are reused for 24 hours.
* **Missing models** – Verify `ollama pull llama3` and `ollama pull nomic-embed-text` have completed successfully.
* **`git pull` refuses to update** – Commit or stash your local changes first (`git status` → `git add ...` → `git commit` or `git stash --include-untracked`), then rerun `git pull origin main`.
* **OCR fallback missing text** – Install Tesseract (`brew install tesseract` on macOS) so `pytesseract` can read scanned PDFs.
* **Still stuck?** – Run `python3 -m yo.cli doctor` to diagnose Python/Ollama/dependency issues automatically, including the minimum `setuptools` version.

---

## 📚 More Docs

See [`USER_GUIDE.md`](USER_GUIDE.md) for an in-depth walkthrough, [`docs/ROADMAP.md`](docs/ROADMAP.md) for the feature roadmap, and [`Yo_Handoff_Report.md`](Yo_Handoff_Report.md) for the latest project status.

---
