# Yo — Conversation Handoff Report

**Repository:** `SeansGravy/Yo`
**Context:** local, fully offline RAG assistant built around **Ollama + Milvus Lite (SQLite) + Python CLI** with optional web awareness and local caching.

---

## 1) Project Purpose (Yo)

**Yo** is a *local second brain*: it ingests your text documents, embeds them, stores them in a local vector DB (Milvus Lite), and answers questions with citations/context—optionally blending in lightweight web snippets. It runs fully offline except when you ask it to fetch web results.

---

## 2) Current Architecture (verified)

* **LLM & Embeddings**: Ollama

  * Generation: `llama3`
  * Embeddings: `nomic-embed-text`
* **Vector DB**: Milvus Lite (file-backed, SQLite) at `data/milvus_lite.db`
* **Orchestration**: lightweight Python with LangChain community loaders + `langchain-ollama`
* **CLI**: `yo/cli.py` (entrypoint: `python3 -m yo.cli ...`)
* **Core Logic**: `yo/brain.py` (ingest, ask, summarize, cache, namespace mgmt)
* **Web-aware**: optional DuckDuckGo HTML scrape (no API key) + 24h JSON cache at `data/web_cache.json`
* **Resilience**:

  * Safe Milvus init + auto-recovery rename if locked
  * Backup rotation for recovered DB snapshots (keep most recent few)

---

## 3) What’s Implemented & Working

### CLI Commands (all tested)

| Command                      | What it does                                                           | Notes                                            |
| ---------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------ |
| `add`                        | Ingest text, Markdown, PDF, and source files into a **namespace**      | Auto-detects format or honor `--loader` override |
| `ask`                        | Retrieve + synthesize answer from a namespace                          | Use `--web` to add live snippets + caching       |
| `summarize`                  | Summarize a namespace’s stored text                                    | Uses LLM (`llama3`)                              |
| `ns list` / `ns delete`      | List or delete collections (namespaces)                                | Delete prompts for confirmation in some variants |
| `cache list` / `cache clear` | Inspect or wipe web cache                                              | Stored at `data/web_cache.json`                  |
| `compact`                    | **VACUUM** the Milvus Lite SQLite DB                                   | Uses Python `sqlite3` VACUUM (serverless-safe)   |
| `doctor`                     | Diagnose local setup (Python, Ollama, dependencies)                    | Highlights missing packages or locked Milvus DB  |
| `verify`                     | Runs `yo_full_test.sh` end-to-end                                      | Writes timestamped `yo_test_results_*.log`       |

### Scripts

* **`yo_full_test.sh`**: full validation (env, add, ask, summarize, web, cache, ns, re-index).
  Produces logs like `yo_test_results_YYYYMMDD_HHMMSS.log`.

### Milvus Lite handling

* Safe reconnection if DB is locked; creates a backup `milvus_lite_recover_*.db`
* Backup rotation to avoid old file sprawl

---

## 4) Known Warnings / Gotchas

* **Ensure modern setuptools** – `python3 -m yo.cli doctor` now checks for `setuptools >= 81` so Milvus Lite stops emitting deprecation warnings.
* **OCR dependencies** – Install `unstructured[local-inference]` and the system Tesseract binary so scanned PDFs ingest correctly.
* **Multiple processes** opening `data/milvus_lite.db` can lock it. If a lock occurs, the safe-init flow renames the file and recreates a fresh DB.
* **Web mode** fetches short HTML snippets (not full content) and caches the results for 24h.

---

## 5) How to Use (quick commands)

Setup (Mac/Linux):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull llama3
ollama pull nomic-embed-text
# Optional: brew install tesseract   # or your distro equivalent for OCR
```

Run:

```bash
# List namespaces (collections)
python3 -m yo.cli ns list

# Ingest a folder of mixed-format files into namespace 'default'
python3 -m yo.cli add ./docs/ --ns default

# Generate sample PDF/XLSX fixtures for demos
python3 scripts/generate_ingest_fixtures.py

# Ingest a scanned PDF with OCR fallback
python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research --loader pdf

# Summarize the namespace
python3 -m yo.cli summarize --ns default

# Ask purely from memory
python3 -m yo.cli ask "What does Yo do?" --ns default

# Ask and blend web context (cached 24h)
python3 -m yo.cli ask "What's new in LangChain 0.3?" --ns default --web

# Manage cache
python3 -m yo.cli cache list
python3 -m yo.cli cache clear

# Compact DB (SQLite VACUUM) — also runs automatically after large ingests
python3 -m yo.cli compact

# Diagnose environment problems
python3 -m yo.cli doctor

# Full regression test
./yo_full_test.sh
python3 -m yo.cli verify
```

---

## 6) Release Status We Reached

* **`v0.2.5`** – Stabilized the ingestion, namespace management, cached web retrieval, and manual compaction flows.
* **`v0.3.0`** – Added Markdown/PDF/code loaders with OCR fallback, the `--loader` override, refreshed embedding imports, auto-compaction thresholds, and warning-free doctor checks.
* **`v0.3.1`** – Delivered graceful degradation when Milvus Lite or the Ollama CLI are missing so verification scripts skip unavailable backends without failing.
* **`v0.4.0`** – Launched the FastAPI Lite UI with backend health indicators, namespace dashboards, and browser-based ingestion uploads.
* **`v0.4.2` (current)** – Realigned documentation under `/docs`, expanded the top-level README, and reaffirmed Milvus Lite as the supported local backend.

---

## 7) Next Work Items (clean, actionable)

**High-value:** (See [`ROADMAP.md`](ROADMAP.md) for the expanded multi-phase plan.)

1. **Lite UI iterations**

   * Add live ingestion progress, richer filtering, and namespace management from the browser.
   * Harden upload handling with resumable transfers and background jobs.

2. **Hybrid retrieval improvements**

   * Support cross-namespace search and ranking, paving the way for blended dashboards.
   * Explore lightweight rerankers to boost answer quality before synthesis.

**Quality-of-life:**
3. **Advanced automation** – Build re-embedding and maintenance commands so schema repairs and model swaps stay simple.
4. **Extended observability** – Capture ingest metrics, chunk counts, and backend health snapshots for long-running deployments.

---

## 8) Useful File Pointers

* `yo/cli.py`: CLI routing for `add`, `ask`, `summarize`, `ns`, `cache`, `compact`, `verify`.
* `yo/brain.py`: All core logic—Milvus safe init/recovery, ingestion (multi-format + OCR), retrieval, summarization, cache, and compaction (auto + manual).
* `yo_full_test.sh`: End-to-end test driver (creates logs).
* `fixtures/ingest/`: Sample Markdown/PDF/code fixtures (generate via `python3 scripts/generate_ingest_fixtures.py`).
* `data/`: Milvus Lite DB + web cache JSON (local artifacts; ignore in git).

---

## 9) Fast Sanity Checklist (for the new session)

* ✅ `python3 -m yo.cli ns list` shows `yo_default` (after ingestion)
* ✅ `python3 -m yo.cli add ./docs/ --ns default` runs without lock errors
* ✅ `python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research --loader pdf` OCRs PDFs when dependencies exist
* ✅ `python3 -m yo.cli ask "What is LangChain?" --ns default` returns coherent text
* ✅ `python3 -m yo.cli ask "..." --web` shows “[Web Results]” in context

---

## 10) Future Considerations

Milvus Lite remains the recommended default for local deployments, balancing portability with zero external services. For larger teams that need concurrency, horizontal scaling, or managed backups, plan an optional migration to a dedicated Milvus standalone or cloud instance. The ingestion and retrieval abstractions in `yo/brain.py` already isolate vector-store calls, so swapping the backend can stay localized to the backend initialization and configuration routines.
* ✅ `python3 -m yo.cli compact` prints a **VACUUM** size delta
* ✅ `python3 -m yo.cli verify` logs and returns “Verification complete”

---

### One-line “ready” test for a fresh shell

```bash
source .venv/bin/activate && python3 -m yo.cli ns list && python3 -m yo.cli add ./docs/ --ns default && python3 scripts/generate_ingest_fixtures.py && python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research --loader pdf && python3 -m yo.cli summarize --ns default
```

---

