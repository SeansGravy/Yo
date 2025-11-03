#!/bin/bash
# Recreate missing documentation files
mkdir -p docs

# --- ROADMAP.md ---
cat > ROADMAP.md <<'EOF'
# Yo Roadmap

## Phase 1 — Core (Done)
- Milvus Lite integration
- CLI: add / ask / summarize
- Web-aware retrieval with caching
- Cache management commands

## Phase 2 — Ingestion & Retrieval Enhancements
- PDF and Markdown ingestion
- Multi-namespace hybrid retrieval
- Auto index verification
- Metadata tagging and filters

## Phase 3 — Reliability & Autonomy
- Namespace management (list, delete, merge)
- Background re-embedding for large docs
- Voice I/O and local agent loop

## Phase 4 — UI & Deployment
- Local FastAPI/Gradio web UI
- Docker Compose packaging
- CI/CD & test coverage
EOF

# --- CHANGELOG.md ---
cat > CHANGELOG.md <<'EOF'
# Changelog

## [v0.2.0] - 2025-11-02
### Added
- Summarization command (`yo summarize`)
- Web-aware retrieval (`yo ask --web`)
- Cache management (`yo cache list`, `yo cache clear`)
### Fixed
- Restored ingestion and summarization after refactor
- Stabilized Milvus Lite schema & index creation
EOF

# --- docs/CLI.md ---
cat > docs/CLI.md <<'EOF'
# Yo CLI Reference

## Add
```bash
python3 -m yo.cli add ./docs/ --ns default
