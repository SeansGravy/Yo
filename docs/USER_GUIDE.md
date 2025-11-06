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

### 4.3 `chat` — Multi-turn conversation

```bash
python3 -m yo.cli chat "Summarize today's ingestion" --ns research
python3 -m yo.cli chat --stream "Explain vector search" --ns research
```

* Maintains a short-term chat history per namespace so follow-up questions stay contextual.
* `--stream` streams tokens as the response is generated—ideal for long answers or demonstrations.
* Rich citations (when available) print beneath each reply so you can trace the source documents quickly.
* The new `/chat` web workspace mirrors the CLI: sessions persist in local storage and token events arrive live via WebSockets.
* If a WebSocket hiccups mid-stream, the UI falls back to the REST reply automatically so you still see the full answer. Set `YO_CHAT_STREAM_FALLBACK=force` to always return full replies without streaming tokens.

### 4.4 `summarize` — Summarize a namespace

```bash
python3 -m yo.cli summarize --ns research
```

* Loads up to 500 stored chunks and asks the LLM for a narrative summary.
* Errors if the namespace is empty or missing.

### 4.5 `namespace` — Manage namespaces

```bash
python3 -m yo.cli namespace list            # alias: `yo ns list`
python3 -m yo.cli namespace switch research
python3 -m yo.cli namespace purge scratch
```

* `list` highlights every namespace and marks the active namespace that other commands target by default.
* `switch <name>` updates the active namespace, persisting the choice to `data/namespace_state.json` and pointing the local web cache at a namespace-specific file.
* `purge <name>` drops the Milvus collection, prunes namespace metadata, and automatically falls back to a safe active namespace.

### 4.6 `config` — Manage defaults

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
* Advanced tuning knobs are exposed via `.env`: `YO_CHUNK_SIZE` / `YO_CHUNK_OVERLAP` alter ingestion chunking behaviour, while `YO_CHAT_STREAM_FALLBACK` controls whether chat replies stream (`auto`/`off`) or return full responses immediately (`force`).

### 4.7 `cache` — Inspect or clear web cache

```bash
python3 -m yo.cli cache list
python3 -m yo.cli cache clear
```

* `list` prints cached queries with timestamps.
* `clear` removes `data/web_cache.json` if it exists.

### 4.8 `compact` — Vacuum the database

```bash
python3 -m yo.cli compact
```

* Runs SQLite `VACUUM` on `data/milvus_lite.db` to reclaim space.
* Prints the size delta (MiB before/after).
* Yo automatically triggers compaction when the database grows beyond ~100 MiB after ingestion.

### 4.9 `doctor` — Diagnose local setup issues

```bash
python3 -m yo.cli doctor
```

* Prints ✅/⚠️/❌ statuses for Python, `langchain`, `langchain-ollama>=0.1.0`, `setuptools>=81`, and `milvus-lite>=2.4.4`.
* Verifies that Ollama, the Ollama Python bindings, `pymilvus[milvus_lite]`, `yo_full_test.sh`, and the `data/` directory are present.
* Reports whether the Milvus Lite runtime can be imported so vector-store operations don’t fail later.
* Attempts to initialize `YoBrain` so Milvus Lite connectivity problems show up immediately.

### 4.10 `verify` — Run the regression suite

```bash
python3 -m yo.cli verify
```

* Executes `yo_full_test.sh` (if the script is present).
* Logs the output to `yo_test_results_<timestamp>.log`.
* Automatically skips ingestion and Q&A checks when Milvus Lite or the Ollama backend is missing, marking those sections with ⚠️ entries instead of failing the suite.
* Persists telemetry under `data/logs/` (`test_summary.json`, `test_history.json`, `dependency_history.json`, `telemetry_summary.json`) and prints a banner summarizing release/namespace/health if Rich is available.

### 4.11 `verify signature` — Confirm artifact authenticity

```bash
python3 -m yo.cli verify signature
python3 -m yo.cli verify signature --json
```

* Validates the detached GPG signature (`data/logs/checksums/artifact_hashes.sig`) against the checksum manifest created during the last green verification run.
* Prints the signer identity, release version, commit SHA, and health score on success; JSON mode emits the same payload for CI gates or scripted tooling.
* Surfaces actionable guidance when signatures are missing or invalid—including reminders to run `yo cli verify` or fetch the latest signed artifacts.

### 4.12 `verify clone` — Validate a fresh checkout

```bash
python3 -m yo.cli verify clone
python3 -m yo.cli verify clone --json
```

* Reuses signature validation and compares `artifact_hashes.txt` with `origin/main` to prove a cloned or restored workspace matches the published artifacts.
* Reports the most recent ledger entry (version, commit SHA, timestamp) pulled from `data/logs/verification_ledger.jsonl`.
* Provides remediation hints when hashes drift, including rerunning `yo deps repair`, discarding local modifications, or pulling updated artifacts.

### 4.13 `verify ledger` — Inspect signed history

```bash
python3 -m yo.cli verify ledger
```

* Prints up to ten of the latest verification ledger entries in reverse chronological order.
* Each entry includes timestamp, release version, commit hash, health score, checksum manifest path, and signature file so audits and manual verification stay traceable.

### 4.14 `verify manifest` — Validate release manifest

```bash
python3 -m yo.cli verify manifest
python3 -m yo.cli verify manifest --json
```

* Confirms `data/logs/integrity_manifest.json` exists and can be parsed, verifies both checksum and release bundle signatures, and recomputes the recorded bundle hash.
* Useful after cloning or restoring an environment—`--json` feeds CI checks while the human-readable output highlights any missing files or signature mismatches.
* Combine with `yo verify signature` to double-check checksum authenticity before ingesting artifacts into another environment.

### 4.15 `package` — Build signed release bundles

```bash
python3 -m yo.cli package release
python3 -m yo.cli package release --version v0.5.0 --signer "Codex CI (auto) <codex-ci@local>"
```

* Collects the checksum manifest, signatures, audit output, telemetry summary, and verification ledger into `releases/release_<version>.tar.gz`, then signs the archive.
* Writes an updated `data/logs/integrity_manifest.json` describing the bundle (version, commit SHA, health score, checksums, signatures).
* Pass `--output` to override the `releases/` directory or `--manifest` to store the manifest elsewhere; `--json` prints machine-readable metadata for CI pipelines.
* After packaging you can distribute the tarball + `.sig` and share the manifest so downstream users can run `yo verify manifest` followed by a direct `gpg --verify`.

### 4.16 `release` — Inspect packaged releases

```bash
python3 -m yo.cli release list
python3 -m yo.cli release info v0.5.0 --json
```

* `list` prints every release recorded under `releases/`, including health score, timestamp, and signed bundle path.
* `info <version>` loads the stored manifest, showing the signer, bundle checksum, and signature paths for that specific build; `--json` emits machine-friendly metadata.
* Combine with `yo package release` to validate packaging before pushing artifacts upstream.

### 4.17 `health` — Review or monitor system status

```bash
python3 -m yo.cli health report
python3 -m yo.cli health monitor --json
```

* `report` combines telemetry averages, dependency activity, and recurring failures into a concise health summary. Use `--json` to feed dashboards or scripts.
* `monitor` enforces freshness thresholds (pass rate ≥ 95 %, latest run < 24 h old), appends results to `data/logs/health_monitor.jsonl`, and exits with a non-zero status on failure so CI can alert operators.
* The scheduled workflow `.github/workflows/health-monitor.yml` runs hourly, uploads the JSONL log as an artifact, and publishes the most recent monitor result in the Actions step summary.

### 4.18 `metrics` — Summarise collected metrics

```bash
python3 -m yo.cli metrics summarize
python3 -m yo.cli metrics summarize --since 24h --json
```

* Aggregates verification duration, pass rate, chat latency, and ingestion throughput from `data/logs/metrics.jsonl`.
* Use `--since` with windows such as `30m`, `24h`, or `7d` to focus on recent behaviour.
* The `/api/metrics` endpoint powers the dashboard metrics panel and returns machine-readable JSON for automation.

### 4.19 `analytics` — Inspect anonymised usage

```bash
python3 -m yo.cli analytics report
python3 -m yo.cli analytics report --since 14d --json
```

* Summarises CLI command usage, chat sessions, and ingestion runs based on `data/logs/analytics.jsonl`.
* Respects `YO_ANALYTICS=off`; set the environment variable to disable tracking entirely.
* `/api/analytics` feeds the dashboard Usage tab so teams can monitor adoption at a glance.

### 4.20 `optimize` — Self-tune configuration

```bash
python3 -m yo.cli optimize suggest
python3 -m yo.cli optimize apply --id ingest_chunk_tuning
```

* `suggest` analyses metrics/analytics to propose safe tweaks (for example lowering chunk size when ingestion slows or forcing chat fallback when latency spikes).
* `apply` writes approved environment updates to `.env` and records every action in `data/logs/optimizer_history.jsonl`.
* Recommendations also appear in `yo health report` and on the dashboard, keeping operators informed about next steps.

### 4.21 `report audit` — Generate compliance reports

```bash
python3 -m yo.cli report audit
python3 -m yo.cli report audit --json
python3 -m yo.cli report audit --md --html
```

* Writes structured JSON/Markdown/HTML audits to `data/logs/audit_report.*`.
* `--json`, `--md`, and `--html` stream the chosen format to stdout.
* Each report includes namespace metrics, dependency drift, lifecycle history, snapshots, and recent test outcomes.
* CI copies the Markdown to `docs/RELEASE_NOTES.md` and publishes the HTML copy at `docs/latest.html` for GitHub Pages.

### 4.22 `system` — Lifecycle tooling

```bash
python3 -m yo.cli system clean --dry-run
python3 -m yo.cli system clean --release
python3 -m yo.cli system snapshot --name rc_candidate
python3 -m yo.cli system restore data/snapshots/rc_candidate.tar.gz
```

* `clean` removes (or previews) stale logs and lock files produced during testing.
* `clean --release` purges previously packaged bundles, manifests, and signatures so you can regenerate artifacts from a clean slate before publishing.
* `snapshot` archives configuration, telemetry, and logs alongside hash metadata.
* `restore` safely unpacks snapshots (with path validation) and logs the event to `data/logs/lifecycle_history.json`.

### 4.23 `logs` — Tail persistent history

```bash
python3 -m yo.cli logs tail --type events
python3 -m yo.cli logs tail --type chat --json --lines 5
```

* Logs from chats, shell sessions, and event broadcasts are persisted under `data/logs/sessions/` with daily JSONL files. They survive restarts for root-cause analysis.
* `tail` picks the most recent log of the requested type (`events`, `chat`, or `shell`) and prints a formatted summary; `--json` returns the raw lines for automation.
* Combine with `yo dashboard --events` for a live stream, then fall back to `yo logs tail` when you need to inspect historical context or triage CI failures.

### 4.24 `help` — Discover commands and aliases

```bash
python3 -m yo.cli help
python3 -m yo.cli help namespace
python3 -m yo.cli t     # alias for `yo telemetry analyze`
python3 -m yo.cli h     # alias for `yo health report`
```

* `help` renders categorized command tables (Rich adds color automatically).
* Subcommand help surfaces nested actions like `namespace stats` and `namespace drift`.
* Aliases keep workflows fast; Rich-based color output is bundled via `requirements.txt`.

### 4.25 `shell` — Interactive developer REPL

```bash
python3 -m yo.cli shell
```

* Launches a persistent prompt (`Yo>`) with history stored in `data/logs/shell_history.txt` so common commands are a few keystrokes away.
* Supports built-in verbs such as `chat`, `verify`, `telemetry`, `deps check`, and `config set/get` without leaving the shell.
* `chat --stream` inside the REPL mirrors the CLI flag—tokens print live and citations appear as soon as the model finishes.
* Press `Ctrl+D` or type `exit` when you are done; the REPL never modifies your `.env` unless you explicitly run the config commands.

### 4.26 Troubleshooting: Web Server Hangs

```bash
python3 -m yo.cli web --debug --port 8010
python3 -m yo.cli health web --host 127.0.0.1 --port 8010 --timeout 5
```

* Debug mode enables asyncio tracing, faulthandler dumps (`data/logs/web_deadlock.dump`), and request logs (`data/logs/web_startup.log`).
* Check `data/logs/ws_errors.log` for WebSocket delivery problems.
* If the default port is busy, pick a new one (e.g. `--port 8010`). The CLI refuses to start if the port is already bound and logs a clear error instead of hanging.
* Probe the HTTP and streaming stack directly: `yo health web` confirms `/api/health` is live, `yo health chat` asserts `/api/chat` returns a reply, and `yo health ws` ensures `/ws/chat/<session>` emits a `chat_complete` frame.
* `/api/chat` always returns a `{type: "chat_message", reply: {text: …}}` payload—even after fallbacks—so the browser visibly closes every turn.
* `/chat` should return instantly; if `curl http://localhost:8000/chat` hangs, run `yo health web --timeout 5` (fails when `/chat` exceeds 1 s) and inspect `data/logs/web_startup.log` plus `data/logs/chat_timing.jsonl` with `yo telemetry trace --session <id>` for clues.
* Need to escalate an unresolved chat disconnect? Run `yo logs collect --chat-bug [--har <browser.har>]` to zip startup logs, WebSocket errors, a metrics tail, and any captured HAR files under `data/logs/chat_bug_*.zip`.
* The end-to-end smoke test (`tests/test_web_e2e_port.py`) starts the server in a subprocess and asserts `/api/health`, `/dashboard`, `/api/chat`, and `/ws/chat/*` all respond. Run it locally with `python3 -m pytest tests/test_web_e2e_port.py -q` to replicate production issues.

### 4.27 Fallback Message Contract

Every REST fallback now yields a consistent payload so the browser can always finish rendering the assistant bubble:

```json
{
  "type": "chat_message",
  "session_id": "abc123",
  "namespace": "default",
  "stream": false,
  "fallback": true,
  "reply": { "text": "(Timed out waiting for model response)" },
  "history": [ { "user": "Hi", "assistant": "(Timed out waiting for model response)" } ]
}
```

If the model raises or returns an empty body, Yo substitutes a human-readable placeholder (`(Model returned no text)`, `(Timed out waiting for model response)`, or `[Chat error: …]`). Use `yo telemetry trace --session <id>` to inspect delivery timing across `/api/chat` and the WebSocket stream when debugging silent replies.

### 4.28 Live Chat Verification & Metrics

- Run `python3 -m yo.cli chat verify "ping"` to issue a live `/api/chat` request and capture elapsed time, token count, and fallback state; append `--debug` to print the raw JSON payload.
- The metrics log now includes `chat_live_success_rate` and `chat_tokens_avg`, so `yo metrics summarize` and `yo analytics report` highlight long-term success rates alongside average token counts.
- Combine the CLI probe with `yo health chat --force-fallback` to distinguish infrastructure outages (no reply) from model-level regressions (fallback or empty text).
- Use `yo health stream` to verify that `/ws/chat/<session>` produces token events within the expected timeout; the command reports token counts and fails fast when the stream stalls.

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

## 7. Release Integrity API

Yo’s REST API also publishes release metadata so you can verify bundles without touching the CLI:

- `GET /api/releases` returns every stored manifest together with the latest verification outcome.
- `GET /api/release/latest` returns the newest release entry (mirrors the dashboard badge).
- `GET /api/release/<version>` serves the raw manifest for that version.
- `GET /api/release/<version>/verify` re-runs manifest verification on demand and reports signature + checksum status as JSON.
- `/api/docs` redirects to FastAPI’s OpenAPI schema, making it trivial to explore the endpoints in a browser.

Combine these endpoints with `yo release list` or the dashboard’s Releases table to keep automation and humans aligned on shipped artifacts.

---

## 8. Troubleshooting & Tips

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

## 9. Roadmap Snapshot

See [`ROADMAP.md`](ROADMAP.md) for the detailed feature roadmap and [`Yo_Handoff_Report.md`](Yo_Handoff_Report.md) for the current release status.

---

Happy researching! 🎉
