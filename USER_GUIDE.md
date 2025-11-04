# 🧠 Yo User Guide

Yo is your local second brain. It ingests plain-text documents, stores their embeddings in Milvus Lite, and lets you interrogate that knowledge base offline with an Ollama-powered language model. This guide walks through setup, day-to-day usage, and troubleshooting tips.

---

## 1. Installation

### 1.1 Grab the code

Clone the official repository:

```bash
git clone https://github.com/SeansGravy/Yo.git
cd Yo
```

### 1.2 Prerequisites

* Python 3.10+
* [Ollama](https://ollama.com/download) installed and running locally
* macOS or Linux shell (Windows WSL works too)

### 1.3 Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 1.4 Install dependencies

```bash
pip install -r requirements.txt
```

> **OCR note:** For scanned PDFs, install the Tesseract binary (`brew install tesseract` on macOS, `sudo apt install tesseract-ocr` on Debian/Ubuntu) so `pytesseract` can extract text during ingestion.

### 1.5 Pull required Ollama models

```bash
ollama pull llama3             # generation model
ollama pull nomic-embed-text   # embedding model
```

---

## 2. Project Layout

```
Yo/
├── data/                  # Milvus Lite SQLite store + web cache
│   ├── milvus_lite.db     # main database (auto-created)
│   ├── recoveries/        # locked DB backups (auto-rotated)
│   └── web_cache.json     # cached DuckDuckGo snippets (24h TTL)
├── docs/                  # drop your `.txt` source files here (optional)
├── fixtures/ingest/       # sample Markdown, PDF, and code fixtures used by tests
├── yo/                    # Python package
│   ├── brain.py           # YoBrain orchestration logic
│   └── cli.py             # command-line interface
├── yo_full_test.sh        # optional regression script (called by `verify`)
└── Yo_Handoff_Report.md   # current project context & roadmap
```

---

## 3. Core Concepts

* **Namespaces** – Logical buckets of knowledge. Each namespace maps to a Milvus collection named `yo_<namespace>`. The default is `yo_default`.
* **Chunks** – Documents are split into ~800-character chunks with overlaps for better retrieval.
* **Web cache** – When you run commands with `--web`, Yo scrapes short snippets from DuckDuckGo and caches the results in `data/web_cache.json` for 24 hours.

---

## 4. CLI Reference

All interactions go through the CLI entry point:

```bash
python3 -m yo.cli <command> [options]
```

For a quick refresher on available subcommands at any time:

```bash
python3 -m yo.cli --help
```

### 4.1 `add` — Ingest local files

```bash
python3 -m yo.cli add ./docs/ --ns research
python3 -m yo.cli add fixtures/ingest/roadmap_note.md --ns briefs --loader markdown
python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research --loader pdf
python3 -m yo.cli add fixtures/ingest/example.py --ns code --loader code
```

* Accepts a path to a directory or a single file.
* Supports auto-detection across text, Markdown, PDF, and common source-code extensions.
* Use `--loader` to force a specific parser (`auto`, `text`, `markdown`, `pdf`, `code`).
* Creates the namespace (Milvus collection) if it does not exist.
* Emits the number of chunks created and confirms when ingestion is complete.
* When `unstructured[local-inference]` and `pytesseract` are available, scanned PDFs are OCR'd automatically.

### 4.2 `ask` — Query the knowledge base

```bash
python3 -m yo.cli ask "What is Yo?" --ns research
python3 -m yo.cli ask "Latest LangChain updates" --ns research --web
```

* Retrieves the top matches from Milvus using cosine similarity (inner product).
* Prints the context Yo used before streaming the response.
* `--web` blends cached or freshly-fetched DuckDuckGo snippets (24h TTL).

### 4.3 `summarize` — Summarize a namespace

```bash
python3 -m yo.cli summarize --ns research
```

* Loads up to 500 stored chunks and asks the LLM for a narrative summary.
* Errors if the namespace is empty or missing.

### 4.4 `ns` — Manage namespaces

```bash
python3 -m yo.cli ns list
python3 -m yo.cli ns delete --ns scratch
```

* `list` shows all namespaces currently available.
* `delete` drops the specified namespace and its data after confirmation.

### 4.5 `cache` — Inspect or clear web cache

```bash
python3 -m yo.cli cache list
python3 -m yo.cli cache clear
```

* `list` prints cached queries with timestamps.
* `clear` removes `data/web_cache.json` if it exists.

### 4.6 `compact` — Vacuum the database

```bash
python3 -m yo.cli compact
```

* Runs SQLite `VACUUM` on `data/milvus_lite.db` to reclaim space.
* Prints the size delta (MiB before/after).
* Yo automatically triggers compaction when the database grows beyond ~100 MiB after ingestion.

### 4.7 `doctor` — Diagnose local setup issues

```bash
python3 -m yo.cli doctor
```

* Confirms Python version, Ollama availability, required Python packages, and minimum `setuptools` version.
* Verifies that `yo_full_test.sh` and the `data/` directory are present.
* Attempts to initialize `YoBrain` so Milvus Lite connectivity problems show up immediately.

### 4.8 `verify` — Run the regression suite

```bash
python3 -m yo.cli verify
```

* Executes `yo_full_test.sh` (if the script is present).
* Logs the output to `yo_test_results_<timestamp>.log`.

---

## 5. Example Session

```bash
# 1. Ingest documentation into the default namespace
python3 -m yo.cli add ./docs/ --ns default

# 1b. Add a scanned PDF with explicit OCR loader
python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research --loader pdf

# 2. Ask purely from memory
python3 -m yo.cli ask "Summarize the project goals" --ns default

# 3. Ask with web augmentation
python3 -m yo.cli ask "What's new in LangChain 0.3?" --ns default --web

# 4. Get an overview of everything stored
python3 -m yo.cli summarize --ns default

# 5. Compact the database when it grows large
python3 -m yo.cli compact
```

---

## 6. Troubleshooting & Tips

| Issue | Likely Cause | Fix |
| ----- | ------------ | --- |
| `Source path not found` | Typo in the ingest path | Double-check the file or folder path. |
| "No ingestible documents" | Directory lacks supported formats | Add `.txt`, `.md`, `.pdf`, or common source files, or force a parser with `--loader`. |
| PDF ingested but blank | Missing OCR dependencies | Install `unstructured[local-inference]` (via `pip install -r requirements.txt`) and system Tesseract (`brew install tesseract` or distro equivalent). |
| Milvus Lite lock message | Another process was using the DB | Yo automatically moves the locked DB into `data/recoveries/` and recreates a clean one. |
| `ask` returns no memory results | Namespace missing or empty | Verify ingestion ran successfully and that you used the correct `--ns`. |
| Web lookup failed | Offline or DuckDuckGo blocked | Retry without `--web`, or investigate network connectivity. |
| CLI shows dependency errors | Missing local setup steps | Run `python3 -m yo.cli doctor` to see which requirement is missing. |
| `git pull` would overwrite files | You have local edits not yet saved | Run `git status` to inspect, then either commit (`git add` → `git commit`) or stash (`git stash --include-untracked`) before pulling again. |

**Tip:** Keep `yo_full_test.sh` up-to-date with your end-to-end checks. `yo.cli verify` depends on it.

---

## 7. Roadmap Snapshot

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the detailed feature roadmap and [`Yo_Handoff_Report.md`](Yo_Handoff_Report.md) for the current release status.

---

Happy researching! 🎉
