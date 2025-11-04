# Yo — Conversational Retrieval and Local Intelligence Framework

**Current Release:** v0.4.2 (Documentation Alignment)

Yo is a modular retrieval-augmented generation (RAG) platform with a FastAPI-based Lite UI,
offline embedding pipeline, and local Milvus Lite vector storage.

## 📘 Project Overview
- CLI commands: `yo.cli verify`, `yo.cli doctor`, ingestion pipeline
- Lite UI dashboard at `/ui` for namespace health and uploads
- Graceful backend detection (Milvus Lite / Ollama)
- Self-repairing schema and data persistence

## 🗂️ Documentation
- [User Guide](docs/USER_GUIDE.md) — Usage, ingestion, and verification
- [Roadmap](docs/ROADMAP.md) — Upcoming phases and milestones
- [Handoff Report](docs/Yo_Handoff_Report.md) — Architecture and development history
- [Developer README](docs/README.md) — Detailed architecture and dev setup

## ⚙️ Testing
```bash
python3 -m compileall yo
python3 -m yo.cli verify
./yo_full_test.sh
```

## 🧭 Status

Phase 1.5 complete — Lite UI with backend health and uploads.
