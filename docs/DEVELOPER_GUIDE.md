# Codex Developer Guide

## Codex Post-Execution Hook (v0.6.10+)

Codex now uses a unified finalize hook for structured task logging.
This hook writes full metadata, validates key fields, and reports
missing context data before task archival.

### Required Keys
- 🧠 Version
- 📘 Notes
- ⚙️ Executor

### Validation Enforcement (v0.6.11+)

Codex now refuses to archive a task card if the structured log
block is missing or incomplete. Legacy timestamp append behavior
is fully deprecated.
