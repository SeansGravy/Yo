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

* **`v0.2.5`**: Tagged the stabilized foundation (text ingestion, namespace management, cached web, manual compact).
* **`v0.3.0`** *(current)*: Markdown/PDF/code loaders with OCR fallback, `--loader` override, langchain-ollama import refresh, auto-compaction threshold, warning-free doctor checks, expanded regression suite.

---

## 7) Next Work Items (clean, actionable)

**High-value:** (See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the expanded multi-phase plan.)

1. **Ingestion telemetry & rebuild tools**

   * Surface chunk/doc counts per ingest and capture simple metrics for future dashboards.
   * Add a re-embed command to rebuild namespaces when embedding models change.

2. **Multi-namespace hybrid retrieval**

   * Search across multiple namespaces (`default`, `research`, etc.) and merge results by similarity score.

**Quality-of-life:**
3. **Improve answer content** by adding a second pass synthesis step (ReAct-style) on the retrieved chunks + optional web snippets.
4. **Lite UI spike** for Phase 1.5 (Textual or FastAPI shell) once the RAG foundation settles.

---

## 8) Useful File Pointers

* `yo/cli.py`: CLI routing for `add`, `ask`, `summarize`, `ns`, `cache`, `compact`, `verify`.
* `yo/brain.py`: All core logic—Milvus safe init/recovery, ingestion (multi-format + OCR), retrieval, summarization, cache, and compaction (auto + manual).
* `yo_full_test.sh`: End-to-end test driver (creates logs).
* `fixtures/ingest/`: Sample Markdown/PDF/code fixtures used in regression tests.
* `data/`: Milvus Lite DB + web cache JSON (local artifacts; ignore in git).

---

## 9) Fast Sanity Checklist (for the new session)

* ✅ `python3 -m yo.cli ns list` shows `yo_default` (after ingestion)
* ✅ `python3 -m yo.cli add ./docs/ --ns default` runs without lock errors
* ✅ `python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research --loader pdf` OCRs PDFs when dependencies exist
* ✅ `python3 -m yo.cli ask "What is LangChain?" --ns default` returns coherent text
* ✅ `python3 -m yo.cli ask "..." --web` shows “[Web Results]” in context
* ✅ `python3 -m yo.cli compact` prints a **VACUUM** size delta
* ✅ `python3 -m yo.cli verify` logs and returns “Verification complete”

---

### One-line “ready” test for a fresh shell

```bash
source .venv/bin/activate && python3 -m yo.cli ns list && python3 -m yo.cli add ./docs/ --ns default && python3 -m yo.cli add fixtures/ingest/brochure.pdf --ns research --loader pdf && python3 -m yo.cli summarize --ns default
```

---

