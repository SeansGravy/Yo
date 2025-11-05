# Yo — Conversational Retrieval and Local Intelligence Framework

**Current Release:** v0.4.3 (Rich Ingestion Fixes)

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
- `yo system snapshot [--name release_candidate]` archives configuration, telemetry, and log files to `data/snapshots/…tar.gz`.
- `yo system restore <archive>` safely restores telemetry/config data (with path validation to prevent archive traversal).
- Lifecycle events and snapshot metadata are tracked in `data/logs/lifecycle_history.json` so audits stay reproducible.

## 🧾 Audit Reports & Doc Sync

- `yo report audit (--json | --md | --html)` generates structured JSON, Markdown, and HTML summaries in `data/logs/audit_report.*`.
- The Local CI workflow publishes these artifacts, copies the Markdown into `docs/RELEASE_NOTES.md`, and pushes doc updates alongside the latest tag.
- CI also refreshes `docs/latest.html`, giving GitHub Pages an always-current audit snapshot.

## 🔐 Signature & Clone Verification

- `yo verify signature [--json]` confirms the detached GPG signature in `data/logs/checksums/artifact_hashes.sig` matches the checksum file. Successful runs report the signer, version, and health metadata; JSON mode emits a machine-friendly payload for CI gates.
- `yo verify clone [--json]` validates the signature and compares `artifact_hashes.txt` against `origin/main`, ensuring cloned or restored working copies match the published artifacts. Any mismatch includes remediation hints (e.g., rerun `yo deps repair`).
- `yo verify ledger` prints the most recent signed verification entries from `data/logs/verification_ledger.jsonl`, including timestamp, commit SHA, and checksum path.
- The dashboard surfaces these trust signals via a green “Verified” badge, signer details, and signature timestamp in the Integrity panel, providing at-a-glance assurance that the build is authentic.

## 📦 Release Packaging & Integrity Manifest

- `yo package release [--version v0.5.0] [--signer "Codex CI (auto) <codex-ci@local>"]` gathers signed checksums, telemetry, audits, and the verification ledger into a compressed bundle under `releases/`, then signs the archive and writes `data/logs/integrity_manifest.json`.
- `yo verify manifest [--json]` validates the integrity manifest, confirms signature authenticity for the checksum file and release bundle, and checks bundle hashes against the recorded value—perfect for post-clone assurance or CI gating.
- The manifest powers new REST endpoints (`/api/release/latest` and `/api/release/<version>`) and the dashboard’s trust badge so anyone can download and verify the latest release directly from Yo.
- Docs now include a quick-start snippet for manual GPG verification:
  ```bash
  python3 -m yo.cli verify manifest
  gpg --verify releases/release_v0.5.0.tar.gz.sig releases/release_v0.5.0.tar.gz
  ```

## 🧭 Dynamic Help, Aliases, & Color

- `yo help` shows a categorized command directory. `yo help <command>` drills into subcommands with rich tables.
- Aliases keep muscle memory sharp: `yo t` → `yo telemetry analyze`, `yo h` → `yo health report`.
- Output is colorized when `rich` is available (auto-installed via `requirements.txt`), making summaries and alerts easy to scan in both CLI and CI logs.

## ⚙️ Testing
```bash
python3 -m compileall yo
python3 -m yo.cli verify
./yo_full_test.sh
```

## 🧭 Status

Phase 1.5 complete — Lite UI with backend health, uploads, and robust PDF/XLSX ingestion.
