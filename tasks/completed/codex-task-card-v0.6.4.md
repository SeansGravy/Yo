# Codex Task Card — v0.6.4 — Version Sync & Workflow Documentation

---
id: v0.6.4
status: active
priority: high
author: Sean Gray
assistant: Logos
executor: Codex
reviewer: Sean Gray
created: 2025-11-06
target: main
---

## 🎯 Objective
1. Fix Codex’s version-reporting logic so all build and health outputs show the **current Yo package version** (from `yo/__init__.py`) rather than the hard-coded legacy `v0.3.8`.  
2. Create `docs/DEVELOPER_GUIDE.md` (or append to it if it exists) describing the full Human-in-the-Loop development workflow between **Sean ↔ Logos ↔ Codex**, including folder layout, task execution, and publishing flow.

---

## ⚙️ Implementation Steps

### 1. Version Propagation Fix
- Ensure the current Yo version is stored only in `yo/__init__.py`:
  ```python
  __version__ = "0.6.4"
  ```
- In `yo/cli.py`, `yo/webui.py`, and any echo logic, import that variable:
  ```python
  from yo import __version__
  print(f"🧠 Yo v{__version__}")
  ```
- Remove any hard-coded version strings.

### 2. Update Health and Telemetry
- Make sure `yo cli verify`, `yo cli health report`, and Codex completion echo use the same `__version__`.
- Example expected output:
  ```
  ✅ Codex build complete — Yo current version: 0.6.4
  ```

### 3. Create Developer Guide
**File:** `docs/DEVELOPER_GUIDE.md`  

#### Content Outline:
```
# Yo Developer Guide

## Overview
Yo is developed using a Human-in-the-Loop workflow between Sean (operator), Logos (architect assistant), and Codex (execution engine).

## Folder Structure
/tasks/active/ – pending Codex tasks  
/tasks/completed/ – executed and logged cards  
/tasks/failed/ – errored tasks  
/tasks/templates/ – base task card template

## Workflow
1️⃣ Sean and Logos author a new Codex Task Card (`.md`) in `/tasks/active/`.  
2️⃣ Sean triggers Codex by typing `.` in VS Code or Atlas.  
3️⃣ Codex executes the steps, logs its actions, and moves the card to `/tasks/completed/`.  
4️⃣ Codex prints manual publish commands (`git add/commit/tag/push`).  
5️⃣ Sean reviews verbose output and approves publication.

## Versioning Policy
- Each task increments the minor version (0.6.X).  
- `__init__.py` is the single source of truth.  
- Publish commands tag the repo accordingly.

## Adding a New Team Member
- Ensure they have GitHub read access and Atlas connected.  
- Copy `/tasks/templates/codex-task-card-template.md`.  
- Drop the card into `/tasks/active/` and run `.`.  
```

### 4. Validation
Run `yo version` and verify the CLI and Codex echo the same `0.6.4`.

---

## 🧾 Commit Message
```
release: v0.6.4 — version sync and developer workflow documentation
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.6.4 — version sync and developer workflow documentation"
git tag -a v0.6.4 -m "Yo v0.6.4 — version propagation and developer guide"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.6.4
📘 Developer Guide created at docs/DEVELOPER_GUIDE.md
🧠 Version echo standardized across CLI and Codex
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.4 — version sync and developer workflow documentation"
git tag -a v0.6.4 -m "Yo v0.6.4 — version propagation and developer guide"
git push origin main --tags
───────────────────────────────
Please run these commands to publish to the repository.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T18:21:50.105809
