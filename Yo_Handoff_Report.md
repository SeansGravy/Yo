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
* **Orchestration**: lightweight Python with LangChain community loaders
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
| `add`                        | Ingest `.txt` files into a **namespace** (Milvus collection `yo_<ns>`) | Auto-creates collection & index                  |
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

* **Milvus Lite warning** about `pkg_resources` (setuptools deprecation) is harmless.
  If you want silence: `pip install "setuptools<81"`.
* **Multiple processes** opening `data/milvus_lite.db` can lock it. If a lock occurs, the safe-init flow renames the file and recreates a fresh DB.
* **Web mode** fetches short HTML snippets (not full content) and caches the results for 24h.

---

## 5) How to Use (quick commands)

Setup (Mac/Linux):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -U langchain langchain-community langchain-text-splitters pymilvus ollama requests
ollama pull llama3
ollama pull nomic-embed-text
```

Run:

```bash
# List namespaces (collections)
python3 -m yo.cli ns list

# Ingest a folder of .txt files into namespace 'default'
python3 -m yo.cli add ./docs/ --ns default

# Summarize the namespace
python3 -m yo.cli summarize --ns default

# Ask purely from memory
python3 -m yo.cli ask "What does Yo do?" --ns default

# Ask and blend web context (cached 24h)
python3 -m yo.cli ask "What's new in LangChain 0.3?" --ns default --web

# Manage cache
python3 -m yo.cli cache list
python3 -m yo.cli cache clear

# Compact DB (SQLite VACUUM)
python3 -m yo.cli compact

# Diagnose environment problems
python3 -m yo.cli doctor

# Full regression test
./yo_full_test.sh
python3 -m yo.cli verify
```

---

## 6) Release Status We Reached

* **`v0.2.0`**: stable core RAG; CLI parity; end-to-end tests pass
* Compact switched to **SQLite VACUUM** (works with Milvus Lite)
* Docs added/improved: README, USER_GUIDE, Developer Guide, release summary

---

## 7) Next Work Items (clean, actionable)

**High-value:** (See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the expanded multi-phase plan.)

1. **Auto-compact trigger** after `add` when DB size exceeds a threshold (e.g., 100 MB).

   * Check `data/milvus_lite.db` size post-ingest; run `compact()` if above threshold; keep a single pre-compact backup.

2. **Markdown/PDF ingestion**

   * Add `UnstructuredMarkdownLoader` and `PyPDFLoader`.
   * Extend `ingest()` to detect extension and load accordingly.

3. **Multi-namespace hybrid retrieval**

   * Search across multiple namespaces (`default`, `research`, etc.) and merge results by similarity score.

**Quality-of-life:**
4. **Improve answer content** by adding a second pass synthesis step (ReAct-style) on the retrieved chunks + optional web snippets.
5. **Docs polish**: ensure README and CLI ref reflect all commands (including compact/verify).

---

## 8) Useful File Pointers

* `yo/cli.py`: CLI routing for `add`, `ask`, `summarize`, `ns`, `cache`, `compact`, `verify`.
* `yo/brain.py`: All core logic—Milvus safe init/recovery, ingestion, retrieval, summarization, cache, and compact (SQLite VACUUM).
* `yo_full_test.sh`: End-to-end test driver (creates logs).
* `data/`: Milvus Lite DB + web cache JSON (local artifacts; ignore in git).

---

## 9) Fast Sanity Checklist (for the new session)

* ✅ `python3 -m yo.cli ns list` shows `yo_default` (after ingestion)
* ✅ `python3 -m yo.cli add ./docs/ --ns default` runs without lock errors
* ✅ `python3 -m yo.cli ask "What is LangChain?" --ns default` returns coherent text
* ✅ `python3 -m yo.cli ask "..." --web` shows “[Web Results]” in context
* ✅ `python3 -m yo.cli compact` prints a **VACUUM** size delta
* ✅ `python3 -m yo.cli verify` logs and returns “Verification complete”

---

### One-line “ready” test for a fresh shell

```bash
source .venv/bin/activate && python3 -m yo.cli ns list && python3 -m yo.cli add ./docs/ --ns default && python3 -m yo.cli summarize --ns default
```

---

