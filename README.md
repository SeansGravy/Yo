# Yo — Conversational Retrieval and Local Intelligence Framework

**Current Release:** v0.5.9.0 — Stream relay, telemetry, and health validation.  
• Real-time chat metrics and health API (`/api/health/chat`)

Yo is a modular retrieval-augmented generation (RAG) platform with a FastAPI-based Lite UI,
offline embedding pipeline, and local Milvus Lite vector storage.

## 📘 Project Overview
- CLI commands: `yo.cli verify`, `yo.cli doctor`, ingestion pipeline
- Namespace management: `yo namespace list|switch|purge` with persisted defaults and per-namespace caches
- Lite UI dashboard at `/ui` for namespace health and uploads
- Dev server entry point: `python3 -m yo.webui` (WatchFiles reload with 1.5 s debounce)
- Graceful backend detection (Milvus Lite / Ollama)
- Self-repairing schema and data persistence
- Unified configuration layer accessible via `yo config` (merges `.env`, environment, and CLI overrides)

### 📎 Sample Fixtures

Generate demo-friendly PDF and XLSX files before running the examples below:

```bash
python3 scripts/generate_ingest_fixtures.py
```

## 🗂️ Documentation
- [User Guide](docs/USER_GUIDE.md) — Usage, ingestion, and verification
- [Roadmap](docs/ROADMAP.md) — Upcoming phases and milestones
- [Handoff Report](docs/Yo_Handoff_Report.md) — Architecture and development history
- [Developer README](docs/README.md) — Detailed architecture and dev setup
- [Release Notes](docs/RELEASE_NOTES.md) — Auto-synced audit snapshots per verified release
- [Latest Audit Summary](docs/latest.html) — CI-published HTML report for the most recent verification run
- [Changelog](docs/CHANGELOG.md) — Human-curated highlights for each verified release

## ⚙️ Configuration
- Inspect merged settings with `python3 -m yo.cli config view` (resolves CLI overrides, `.env`, and namespace-specific defaults).
- Update global defaults via `python3 -m yo.cli config set <key> <value>`; namespace-specific overrides accept `--ns`.
- Reset to baseline with `python3 -m yo.cli config reset [key]`.
- `.env.example` documents supported environment variables (`YO_MODEL`, `YO_EMBED_MODEL`, `YO_NAMESPACE`, `YO_DB_URI`, `YO_DATA_DIR`). Copy it to `.env` to pin local preferences.

## 📄 Supported File Types & Dependencies
- Markdown, plain text, and source files — handled automatically via LangChain text loaders.
- PDF — install `unstructured[local-inference]`, `pdfminer.six`, and `chardet>=5.2` for reliable extraction (add `pytesseract` for OCR of scanned pages).
- XLSX spreadsheets — install `openpyxl` alongside `chardet>=5.2` to parse workbook text.
- Lite UI uploads — require `python-multipart>=0.0.9` and `Jinja2>=3.1` for the browser dashboard.

## 🎨 Documentation Personality

Yo isn’t just code — it’s a living experiment in clarity and consciousness.  
To keep the docs readable (and occasionally fun), we encourage a light layer of humor:

> **Guideline:** Season, don’t sauce. Subtle wit > slapstick.

### Examples
🧠 *In Code*
```python
class YoBrain:
    """Second brain. Handles recall, reflection, and the occasional existential crisis."""
# TODO: Resist urge to name this YoMama
```

📚 *In Docs*
“YoMemory never forgets… unless the disk fills up, in which case, oops.”

⚙️ *Easter Eggs*
“If you’re reading this, congratulations — you’ve passed the Turing patience test.”

## 🚀 Quick Start (One-Liner)

Set up a fresh development environment, verify the stack, and launch the dashboard in a single command:

```bash
scripts/setup_yo_dev.sh
```

> The script provisions a virtualenv, installs dependencies, runs the full verification suite, and opens the dashboard so you can confirm everything is ready.

## 📊 Namespace Intelligence

- `yo namespace stats` (alias `yo ns stats`) prints per-namespace totals, deltas, growth %, and ingestion counts with alert thresholds:
  - Documents > **1 000**, chunks > **5 000**, or growth spikes > **75 %** trigger colorized warnings.
- `yo namespace drift --since 7d` highlights recent ingestion deltas over a configurable window (`24h`, `7d`, `2w`, …).
- The Lite UI now mirrors these metrics — the namespaces table shows growth trends, verification status, and alert banners, and `/api/status` exposes the same JSON for tooling.

## 🛠 Lifecycle & Snapshot Tools

- `yo system clean [--dry-run]` removes stale logs and lock files (or previews the files it would delete).
- `yo system clean --release` clears previously packaged bundles and integrity manifests so you can rebuild from a clean slate before tagging.
- `yo system snapshot [--name release_candidate]` archives configuration, telemetry, and log files to `data/snapshots/…tar.gz`.
- `yo system restore <archive>` safely restores telemetry/config data (with path validation to prevent archive traversal).
- Lifecycle events and snapshot metadata are tracked in `data/logs/lifecycle_history.json` so audits stay reproducible.

## 🧾 Audit Reports & Doc Sync

- `yo report audit (--json | --md | --html)` generates structured JSON, Markdown, and HTML summaries in `data/logs/audit_report.*`.
- The Local CI workflow publishes these artifacts, copies the Markdown into `docs/RELEASE_NOTES.md`, and pushes doc updates alongside the latest tag.
- CI also refreshes `docs/latest.html`, giving GitHub Pages an always-current audit snapshot.

## 📡 Monitoring & Persistent Logs

- Chat transcripts, shell sessions, and event broadcasts append to `data/logs/sessions/` so you can inspect history across restarts. Each day receives its own JSONL file.
- `yo logs tail --type events` (or `chat` / `shell`) prints a formatted tail of the latest log; add `--json` for machine-readable output in scripts and CI.
- `yo health monitor [--json]` evaluates the most recent verification run, health score, and update cadence, writing results to `data/logs/health_monitor.jsonl`. A failing status exits with code 1 so CI or CRON jobs can alert immediately.
- The hourly GitHub Actions workflow `.github/workflows/health-monitor.yml` runs the same command and uploads the JSONL log, giving the team a rolling audit of system freshness and pass rates.
- Every chat turn now records emit successes/failures to `data/logs/chat_timing.jsonl`; inspect delivery timelines with `yo telemetry trace --session <id>` when debugging UI silence.

### ♻️ Automatic Ollama Recovery

- Run `python3 -m yo.cli monitor ollama` to keep the local Ollama daemon in check. The watchdog pings the `/api/generate` endpoint every 15 s, restarts the service after two consecutive failures, and appends structured entries to `data/logs/ollama_monitor.log`.
- `yo health ollama [--watch]` performs an on-demand ping, reports uptime %, restart counts, and average latency, and can refresh continuously with `--watch --interval <seconds>`.
- Each restart and ping latency is logged to `metrics.jsonl`, feeding the `/api/health/chat` endpoint and analytics dashboard so unattended deployments surface drift in real time.

## 🧯 Troubleshooting the :8000 Hang

- Launch with instrumentation: `python3 -m yo.cli web --debug --port 8010` (or `yo web --debug --port 8010`). Debug mode enables asyncio tracing, faulthandler dumps, and request logging to `data/logs/web_startup.log`.
- If the server stalls, inspect `data/logs/web_startup.log`, `data/logs/ws_errors.log`, and `data/logs/web_deadlock.dump` for the stuck coroutine.
- Every `/api/chat` call now returns a `{type: "chat_message", reply: {text: …}}` payload—fallbacks included—so the browser always renders a visible assistant bubble.
- If a model stalls or returns `{}`, the fallback path injects a readable placeholder like `(Timed out waiting for model response)` instead of leaving the bubble blank.
- Quickly verify availability with `yo health web --host 127.0.0.1 --port 8010 --timeout 5`; follow up with `yo health chat` / `yo health ws` to assert `/api/chat` replies and `/ws/chat` streams produce tokens.
- `/chat` should render immediately. If a plain `curl http://127.0.0.1:8010/chat` hangs or takes >1s, rerun `yo health web` (now checks `/chat` latency) and inspect `data/logs/web_startup.log` + `data/logs/chat_timing.log` for slow renders.
- Capture a reproducible diagnostics bundle with `yo logs collect --chat-bug [--har <browser.har>]`—the ZIP contains recent startup logs, WebSocket errors, metrics tail, and optional HAR traces under `data/logs/`.
- The automated smoke test (`tests/test_web_e2e_port.py`) starts the server on a real port, hits `/api/health`, `/dashboard`, `/api/chat`, and `/ws/chat/*`. Run it locally with `python3 -m pytest tests/test_web_e2e_port.py -q` to reproduce environment issues.

## 📈 Metrics & Analytics

- `yo metrics summarize --since 24h` aggregates verification duration, pass rate, chat latency, and ingestion throughput from `data/logs/metrics.jsonl`. The Lite UI hits `/api/metrics` to populate the new Metrics panel automatically.
- `yo analytics report --since 14d` surfaces CLI command frequency, chat sessions, and ingestion activity (respects `YO_ANALYTICS=off`). `/api/analytics` powers the dashboard Usage tab and returns JSON summaries for custom tooling.
- Metrics and analytics refresh in real time on `/dashboard` and in `yo dashboard --live`, so you can keep an eye on trends without leaving the terminal.

## 🤖 Self-Optimization

- `yo optimize suggest` analyses recent metrics and analytics to recommend safe configuration tweaks (for example lowering chunk sizes when ingestion slows).
- `yo optimize apply [--id <recommendation>]` writes approved tweaks into `.env`, logging every change to `data/logs/optimizer_history.jsonl`. Current actions include tuning `YO_CHUNK_SIZE` / `YO_CHUNK_OVERLAP` and forcing chat fallback via `YO_CHAT_STREAM_FALLBACK=force` when latency spikes.
- Ingestion honours the new environment knobs automatically; reducing `YO_CHUNK_SIZE` decreases embedding payload size without requiring code edits.
- `yo health report` now includes the top optimisation suggestions so operators know which action to take next.

## 💬 Live Chat Verification & Metrics

- `yo chat verify "ping"` issues a live `/api/chat` request and prints elapsed time, token count, and whether fallback fired.
- Use `yo chat verify --debug` to inspect the raw JSON payload returned by the API for deeper diagnostics.
- New metrics `chat_live_success_rate` and `chat_tokens_avg` surface in `yo metrics summarize` and `yo analytics report`, allowing CI and dashboards to alert whenever live replies dip below the expected success threshold.
- `yo health stream --host 127.0.0.1 --port 8000` exercises the WebSocket path end-to-end, failing fast if no tokens arrive within 10 seconds.

## 🔐 Signature & Clone Verification

- `yo verify signature [--json]` confirms the detached GPG signature in `data/logs/checksums/artifact_hashes.sig` matches the checksum file. Successful runs report the signer, version, and health metadata; JSON mode emits a machine-friendly payload for CI gates.
- `yo verify clone [--json]` validates the signature and compares `artifact_hashes.txt` against `origin/main`, ensuring cloned or restored working copies match the published artifacts. Any mismatch includes remediation hints (e.g., rerun `yo deps repair`).
- `yo verify ledger` prints the most recent signed verification entries from `data/logs/verification_ledger.jsonl`, including timestamp, commit SHA, and checksum path.
- The dashboard surfaces these trust signals via a green “Verified” badge, signer details, and signature timestamp in the Integrity panel, providing at-a-glance assurance that the build is authentic.

## 📦 Release Packaging & Integrity Manifest

- `yo package release [--version v0.5.0] [--signer "Codex CI (auto) <codex-ci@local>"]` gathers signed checksums, telemetry, audits, and the verification ledger into a compressed bundle under `releases/`, then signs the archive and writes `data/logs/integrity_manifest.json`.
- `yo verify manifest [--json]` validates the integrity manifest, confirms signature authenticity for the checksum file and release bundle, and checks bundle hashes against the recorded value—perfect for post-clone assurance or CI gating.
- `yo release list` and `yo release info <version>` surface every packaged bundle, including signer metadata, health score, and signed artifact paths.
- The manifest powers new REST endpoints (`/api/releases`, `/api/release/<version>`, `/api/release/<version>/verify`) and the dashboard’s trust badge so anyone can download and verify the latest release directly from Yo.
- A scheduled CI workflow (`release-verification.yml`) re-runs manifest verification daily, writes `data/logs/release_verification.json`, and appends a `recheck: true` entry to the ledger—Actions summaries highlight the latest pass/fail state automatically.
- Docs now include a quick-start snippet for manual GPG verification:
  ```bash
  python3 -m yo.cli verify manifest
  gpg --verify releases/release_v0.5.0.tar.gz.sig releases/release_v0.5.0.tar.gz
  ```

## 🧭 Dynamic Help, Aliases, & Color

- `yo help` shows a categorized command directory. `yo help <command>` drills into subcommands with rich tables.
- Aliases keep muscle memory sharp: `yo t` → `yo telemetry analyze`, `yo h` → `yo health report`.
- Output is colorized when `rich` is available (auto-installed via `requirements.txt`), making summaries and alerts easy to scan in both CLI and CI logs.

## 💬 Conversational CLI & UI

- `yo chat [message] [--ns research]` opens a multi-turn REPL that preserves history, surfaces citations, and mirrors the new `/chat` web workspace.
- `yo chat --stream "Explain RAG"` prints tokens as soon as the model generates them; the web UI receives the same token events over `/ws/chat/<session>`.
- `yo shell` launches an always-on developer console with history, auto-completion (when available), and shortcuts for `verify`, `telemetry analyze`, `deps check`, and more.
- `/chat` in the Lite UI keeps a persistent message list, streams responses as they arrive, and remembers the current session via local storage.
- The chat UI now falls back to the REST payload automatically if WebSocket streaming is interrupted, so the assistant bubble never blanks out mid-reply (`YO_CHAT_STREAM_FALLBACK=force` disables streaming entirely when needed).
- Real-time dashboards now run over `/ws/updates`; `yo dashboard --live` brings those pulses to the terminal, `yo dashboard --events` streams the event feed, and `yo logs tail --type events` inspects the persisted history in `data/logs/sessions/events_*`.

## ⚙️ Testing
```bash
python3 -m compileall yo
python3 -m yo.cli verify
./yo_full_test.sh
```

## 🧭 Status

Phase 1.5 complete — Lite UI with backend health, uploads, and robust PDF/XLSX ingestion.
