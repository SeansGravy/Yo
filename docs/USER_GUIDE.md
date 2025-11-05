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

* Python 3.9+ (3.10+ recommended)
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

> The requirements file installs `langchain-ollama>=0.1.0`, `milvus-lite>=2.4.4`, and pins `setuptools>=81` so the Milvus Lite backend stays compatible out of the box.

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
├── data/                  # Milvus Lite SQLite store, namespace state, and logs
│   ├── milvus_lite.db     # main database (auto-created)
│   ├── recoveries/        # locked DB backups (auto-rotated)
│   ├── logs/              # structured log output (yo.log with rotation)
│   ├── namespace_state.json  # active namespace persisted for CLI defaults
│   └── web_cache*.json    # per-namespace cached DuckDuckGo snippets (24h TTL)
├── docs/
│   ├── README.md          # developer overview and architecture
│   ├── USER_GUIDE.md      # this guide
│   ├── ROADMAP.md         # upcoming phases and milestones
│   └── Yo_Handoff_Report.md   # current project context & release history
├── fixtures/ingest/       # sample Markdown/PDF/code fixtures (run scripts/generate_ingest_fixtures.py)
├── yo/                    # Python package
│   ├── __init__.py        # warning filters + package metadata
│   ├── brain.py           # YoBrain orchestration logic
│   ├── cli.py             # command-line interface
│   └── webui.py           # FastAPI stub for the Lite UI
├── yo_full_test.sh        # optional regression script (called by `verify`)
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
python3 scripts/generate_ingest_fixtures.py  # generate sample PDF/XLSX fixtures
python3 -m yo.cli add ./docs/ --ns research
python3 -m yo.cli add fixtures/ingest/roadmap_note.md --ns briefs
python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research
python3 -m yo.cli add fixtures/ingest/sample.xlsx --ns finance
python3 -m yo.cli add fixtures/ingest/example.py --ns code
```

* Accepts a path to a directory or a single file.
* Supports auto-detection across text, Markdown, PDF, XLSX, and common source-code extensions.
* Creates the namespace (Milvus collection) if it does not exist.
* Emits the number of chunks created and confirms when ingestion is complete.
* PDF ingestion requires `unstructured[local-inference]`, `pdfminer.six`, and `chardet>=5.2`. Install `pytesseract` plus the Tesseract binary for OCR of scanned pages.
* XLSX ingestion requires `openpyxl` alongside `chardet>=5.2`.
* When dependencies are missing or a format is unsupported, the CLI and Lite UI now return clear error messages instead of aborting the entire run.
* Detailed ingestion diagnostics (chunk counts, durations, and tracebacks) are written to `data/logs/yo.log` so you can audit long-running imports.

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

### 4.4 `namespace` — Manage namespaces

```bash
python3 -m yo.cli namespace list            # alias: `yo ns list`
python3 -m yo.cli namespace switch research
python3 -m yo.cli namespace purge scratch
```

* `list` highlights every namespace and marks the active namespace that other commands target by default.
* `switch <name>` updates the active namespace, persisting the choice to `data/namespace_state.json` and pointing the local web cache at a namespace-specific file.
* `purge <name>` drops the Milvus collection, prunes namespace metadata, and automatically falls back to a safe active namespace.

### 4.5 `config` — Manage defaults

```bash
python3 -m yo.cli config view
python3 -m yo.cli config set model ollama:llama3
python3 -m yo.cli config set embed_model ollama:nomic-embed-text --ns research
python3 -m yo.cli config reset --ns research
```

* `view` prints the merged configuration for the active (or specified) namespace, showing the precedence of CLI overrides, `.env`, environment variables, and namespace metadata.
* `set <key> <value>` persists a change. Without `--ns` the setting is stored in `.env`. With `--ns` the override is written to `data/namespace_meta.json` beside ingestion metrics.
* `reset [key]` removes overrides globally or for a namespace so YoBrain falls back to defaults (`ollama:llama3` and `ollama:nomic-embed-text`).
* `.env.example` lists recognised variables (`YO_MODEL`, `YO_EMBED_MODEL`, `YO_NAMESPACE`, `YO_DB_URI`, `YO_DATA_DIR`, and optional cloud API keys). Copy it to `.env` to pin local defaults.

### 4.6 `cache` — Inspect or clear web cache

```bash
python3 -m yo.cli cache list
python3 -m yo.cli cache clear
```

* `list` prints cached queries with timestamps.
* `clear` removes `data/web_cache.json` if it exists.

### 4.7 `compact` — Vacuum the database

```bash
python3 -m yo.cli compact
```

* Runs SQLite `VACUUM` on `data/milvus_lite.db` to reclaim space.
* Prints the size delta (MiB before/after).
* Yo automatically triggers compaction when the database grows beyond ~100 MiB after ingestion.

### 4.8 `doctor` — Diagnose local setup issues

```bash
python3 -m yo.cli doctor
```

* Prints ✅/⚠️/❌ statuses for Python, `langchain`, `langchain-ollama>=0.1.0`, `setuptools>=81`, and `milvus-lite>=2.4.4`.
* Verifies that Ollama, the Ollama Python bindings, `pymilvus[milvus_lite]`, `yo_full_test.sh`, and the `data/` directory are present.
* Reports whether the Milvus Lite runtime can be imported so vector-store operations don’t fail later.
* Attempts to initialize `YoBrain` so Milvus Lite connectivity problems show up immediately.

### 4.9 `verify` — Run the regression suite

```bash
python3 -m yo.cli verify
```

* Executes `yo_full_test.sh` (if the script is present).
* Logs the output to `yo_test_results_<timestamp>.log`.
* Automatically skips ingestion and Q&A checks when Milvus Lite or the Ollama backend is missing, marking those sections with ⚠️ entries instead of failing the suite.
* Persists telemetry under `data/logs/` (`test_summary.json`, `test_history.json`, `dependency_history.json`, `telemetry_summary.json`) and prints a banner summarizing release/namespace/health if Rich is available.

### 4.10 `verify signature` — Confirm artifact authenticity

```bash
python3 -m yo.cli verify signature
python3 -m yo.cli verify signature --json
```

* Validates the detached GPG signature (`data/logs/checksums/artifact_hashes.sig`) against the checksum manifest created during the last green verification run.
* Prints the signer identity, release version, commit SHA, and health score on success; JSON mode emits the same payload for CI gates or scripted tooling.
* Surfaces actionable guidance when signatures are missing or invalid—including reminders to run `yo cli verify` or fetch the latest signed artifacts.

### 4.11 `verify clone` — Validate a fresh checkout

```bash
python3 -m yo.cli verify clone
python3 -m yo.cli verify clone --json
```

* Reuses signature validation and compares `artifact_hashes.txt` with `origin/main` to prove a cloned or restored workspace matches the published artifacts.
* Reports the most recent ledger entry (version, commit SHA, timestamp) pulled from `data/logs/verification_ledger.jsonl`.
* Provides remediation hints when hashes drift, including rerunning `yo deps repair`, discarding local modifications, or pulling updated artifacts.

### 4.12 `verify ledger` — Inspect signed history

```bash
python3 -m yo.cli verify ledger
```

* Prints up to ten of the latest verification ledger entries in reverse chronological order.
* Each entry includes timestamp, release version, commit hash, health score, checksum manifest path, and signature file so audits and manual verification stay traceable.

### 4.13 `report audit` — Generate compliance reports

```bash
python3 -m yo.cli report audit
python3 -m yo.cli report audit --json
python3 -m yo.cli report audit --md --html
```

* Writes structured JSON/Markdown/HTML audits to `data/logs/audit_report.*`.
* `--json`, `--md`, and `--html` stream the chosen format to stdout.
* Each report includes namespace metrics, dependency drift, lifecycle history, snapshots, and recent test outcomes.
* CI copies the Markdown to `docs/RELEASE_NOTES.md` and publishes the HTML copy at `docs/latest.html` for GitHub Pages.

### 4.14 `system` — Lifecycle tooling

```bash
python3 -m yo.cli system clean --dry-run
python3 -m yo.cli system snapshot --name rc_candidate
python3 -m yo.cli system restore data/snapshots/rc_candidate.tar.gz
```

* `clean` removes (or previews) stale logs and lock files produced during testing.
* `snapshot` archives configuration, telemetry, and logs alongside hash metadata.
* `restore` safely unpacks snapshots (with path validation) and logs the event to `data/logs/lifecycle_history.json`.

### 4.15 `help` — Discover commands and aliases

```bash
python3 -m yo.cli help
python3 -m yo.cli help namespace
python3 -m yo.cli t     # alias for `yo telemetry analyze`
python3 -m yo.cli h     # alias for `yo health report`
```

* `help` renders categorized command tables (Rich adds color automatically).
* Subcommand help surfaces nested actions like `namespace stats` and `namespace drift`.
* Aliases keep workflows fast; Rich-based color output is bundled via `requirements.txt`.

---

## 5. Example Session

```bash
# 1. Ingest documentation into the default namespace
python3 -m yo.cli add ./docs/ --ns default

# 1b. Add a scanned PDF once OCR dependencies are installed
python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research

# 1c. Add an XLSX workbook (requires openpyxl + chardet)
python3 -m yo.cli add fixtures/ingest/sample.xlsx --ns finance

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

## 6. Lite Web UI Preview

The Lite UI now ships with a FastAPI app in `yo/webui.py`. Launch it with the bundled reload supervisor:

```bash
python3 -m yo.webui
```

The wrapper runs Uvicorn behind a WatchFiles reloader (1.5 s debounce) that ignores transient edits to `tests/test_memory.py`, preventing runaway restart loops during test runs. If WatchFiles is unavailable, the command falls back to a standard Uvicorn server.

Open [http://localhost:8000/ui](http://localhost:8000/ui) to:

* Review Milvus Lite and Ollama health (including detected versions) at a glance.
* Inspect each namespace’s last-ingested timestamp along with cumulative document and chunk counts.
* Upload one or more files directly into any namespace—select the target namespace, choose your files, and the UI will call the same ingestion pipeline used by the CLI. The uploader is disabled automatically when Milvus Lite or Ollama are missing, and the warning panel explains what needs to be installed.
  * File uploads rely on the optional `python-multipart` package (bundled in `requirements.txt`) and the Jinja2 templating engine. If you install dependencies manually, add them via `pip install python-multipart Jinja2` so the browser uploader works.

Need machine-readable data? Hit [http://localhost:8000/api/status](http://localhost:8000/api/status) for JSON containing backend readiness, namespace metrics, and the ingestion enablement flag the UI relies on.

---

## 7. Troubleshooting & Tips

| Issue | Likely Cause | Fix |
| ----- | ------------ | --- |
| `Source path not found` | Typo in the ingest path | Double-check the file or folder path. |
| "No ingestible documents" | Directory lacks supported formats | Add `.txt`, `.md`, `.pdf`, `.xlsx`, or common source files. |
| `Install chardet` / `Install openpyxl` errors | Optional parser dependency missing | Install the suggested package (`pip install chardet` or `pip install openpyxl`) and rerun ingestion. |
| PDF ingested but blank | Missing OCR dependencies | Install `unstructured[local-inference]` (via `pip install -r requirements.txt`) and system Tesseract (`brew install tesseract` or distro equivalent). |
| Milvus Lite lock message | Another process was using the DB | Yo automatically moves the locked DB into `data/recoveries/` and recreates a clean one. |
| `ask` returns no memory results | Namespace missing or empty | Verify ingestion ran successfully and that you used the correct `--ns`. |
| Web lookup failed | Offline or DuckDuckGo blocked | Retry without `--web`, or investigate network connectivity. |
| CLI shows dependency errors | Missing local setup steps | Run `python3 -m yo.cli doctor` to see which requirement is missing. |
| `yo.cli verify` reports skipped steps | Milvus Lite or the Ollama backend is not installed | Install `pymilvus[milvus_lite]` plus the Ollama CLI and Python bindings (`pip install ollama langchain-ollama`) to run the full suite. |
| `git pull` would overwrite files | You have local edits not yet saved | Run `git status` to inspect, then either commit (`git add` → `git commit`) or stash (`git stash --include-untracked`) before pulling again. |

**Tip:** Keep `yo_full_test.sh` up-to-date with your end-to-end checks. `yo.cli verify` depends on it.

---

## 8. Roadmap Snapshot

See [`ROADMAP.md`](ROADMAP.md) for the detailed feature roadmap and [`Yo_Handoff_Report.md`](Yo_Handoff_Report.md) for the current release status.

---

Happy researching! 🎉
