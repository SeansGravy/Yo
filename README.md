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

## ⚙️ Testing
```bash
python3 -m compileall yo
python3 -m yo.cli verify
./yo_full_test.sh
```

## 🧭 Status

Phase 1.5 complete — Lite UI with backend health, uploads, and robust PDF/XLSX ingestion.
