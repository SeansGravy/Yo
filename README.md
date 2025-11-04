# Yo — Conversational Retrieval and Local Intelligence Framework

**Current Release:** v0.4.3 (Rich Ingestion Fixes)

Yo is a modular retrieval-augmented generation (RAG) platform with a FastAPI-based Lite UI,
offline embedding pipeline, and local Milvus Lite vector storage.

## 📘 Project Overview
- CLI commands: `yo.cli verify`, `yo.cli doctor`, ingestion pipeline
- Lite UI dashboard at `/ui` for namespace health and uploads
- Graceful backend detection (Milvus Lite / Ollama)
- Self-repairing schema and data persistence

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

## 📄 Supported File Types & Dependencies
- Markdown, plain text, and source files — handled automatically via LangChain text loaders.
- PDF — install `unstructured[local-inference]`, `pdfminer.six`, and `chardet>=5.2` for reliable extraction (add `pytesseract` for OCR of scanned pages).
- XLSX spreadsheets — install `openpyxl` alongside `chardet>=5.2` to parse workbook text.
- Lite UI uploads — require `python-multipart>=0.0.9` and `Jinja2>=3.1` for the browser dashboard.

## ⚙️ Testing
```bash
python3 -m compileall yo
python3 -m yo.cli verify
./yo_full_test.sh
```

## 🧭 Status

Phase 1.5 complete — Lite UI with backend health, uploads, and robust PDF/XLSX ingestion.
