# Codex Task Card — v0.6.12 — Unify Version Source and Fix Publish Echo

---
id: v0.6.12
status: active
priority: critical
author: Sean Gray
assistant: Logos
executor: Codex
reviewer: Sean Gray
created: 2025-11-06
target: main
---

## 🎯 Objective
Ensure **Codex** always reports the correct **Yo** version across *every* context (console banner, structured append block, and publish tag) by centralizing version retrieval in `yo/__init__.py` and replacing all legacy constants or cached imports. This card also requires Codex to **confirm** the import path it uses for version echo at runtime.

---

## ⚙️ Implementation Steps

### 1) Centralize the version string (single source of truth)
**File:** `yo/__init__.py`
```python
__version__ = "0.6.12"
```

### 2) Create a unified accessor (explicit import contract)
**File:** `yo/utils/version.py`
```python
from yo import __version__

def get_yo_version() -> str:
    """Return the canonical Yo version string from yo/__init__.py."""
    return __version__
```

### 3) Refactor ALL version references to use the accessor
Search for any of the following patterns and replace them:
- Hardcoded strings: `"🧠 Yo v0.3.8"`, `YO_VERSION = "0.3.8"`
- Direct prints/formatting using stale imports

Replace with:
```python
from yo.utils.version import get_yo_version
print(f"🧠 Yo v{get_yo_version()} | Namespace: {namespace} | Health: {health} | Pass Rate: {pass_rate}%")
```

**Files to update (at minimum):**
- `yo/cli.py`
- `yo/hooks/codex_finalize.py`
- `yo/webui.py`
- any GitHub Action/workflow summaries (if they echo the version)
- any Codex packaging or publish step that forms a tag message

### 4) Update Codex finalize hook to use the accessor
**File:** `yo/hooks/codex_finalize.py`
```python
from yo.utils.version import get_yo_version

def finalize_task(card_path, context):
    context["version"] = get_yo_version()
    # (rest of finalize logic unchanged: build context, append, validate)
```

### 5) Runtime confirmation (MANDATORY console echo)
At the start of a run and again at finalize, Codex must print the import path & the resolved version:
```
[Codex] Version source: yo/__init__.py via yo.utils.version.get_yo_version()
[Codex] Resolved Yo version: 0.6.12
```

### 6) Cache/Session reset (to defeat stale imports)
Codex must clear any stale module caches *or* restart its session after refactor so that:
- old `yo.cli` imports do not shadow the accessor,
- the banner and structured append both show the same value.

**If Codex is running in a persistent process:** restart after step 3.

### 7) Structured append must include the correct version
The appended block in the completed task card MUST contain:
```
🧠 Version: 0.6.12
```
and **never** fallback to legacy values. If mismatch detected, Codex should print:
```
[Codex] ⚠️ Version mismatch: append=..., expected=0.6.12 (aborting archive)
```
and refuse to archive until corrected.

---

## 🧪 Tests

### A) Unit: version sync
**File:** `tests/test_version_sync.py`
```python
from yo.utils.version import get_yo_version
from yo import __version__

def test_version_sync():
    assert get_yo_version() == __version__
```

### B) Integration: finalize append includes canonical version
**File:** `tests/test_finalize_version_in_append.py`
```python
from pathlib import Path
from yo.hooks.codex_finalize import finalize_task
from yo.utils.version import get_yo_version

def test_finalize_includes_correct_version(tmp_path: Path):
    card = tmp_path / "card.md"
    card.write_text("# test\n")
    ctx = {"operator": "Sean Gray", "cwd": str(tmp_path), "scan_path": str(tmp_path)}
    finalize_task(card, ctx)
    txt = card.read_text()
    assert f"🧠 Version: {get_yo_version()}" in txt
```

---

## 📘 Documentation Update
Append to `docs/DEVELOPER_GUIDE.md`:
```markdown
### Version Management (v0.6.12+)
- The Yo version is defined only in `yo/__init__.py`.
- All modules (CLI, Web UI, Codex finalize hook, and summaries) must import the version via
  `yo.utils.version.get_yo_version()`.
- Codex prints the resolved version and its source module at runtime for audit.
```

---

## 🔎 Operator Verification Checklist
1. Place this card into `/tasks/active/` and run `.`
2. Confirm console prints:
   - `Version source: yo/__init__.py via yo.utils.version.get_yo_version()`
   - `Resolved Yo version: 0.6.12`
3. Open `/tasks/completed/codex-task-card-v0.6.12.md` and confirm:
   - `🧠 Version: 0.6.12` in the structured block
   - No legacy `0.3.8` anywhere

If any mismatch appears, Codex must restart its runtime and re-run the task after correcting imports.

---

## 🧾 Commit Message
```
release: v0.6.12 — unify version source for Codex and Yo, fix publish echo
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.6.12 — unify version source for Codex and Yo, fix publish echo"
git tag -a v0.6.12 -m "Yo v0.6.12 — unified version source for Codex and Yo"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.6.12
🧠 Version source: yo/__init__.py via yo.utils.version.get_yo_version()
📘 All echoes and publish tags now reflect the correct version
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.12 — unify version source for Codex and Yo, fix publish echo"
git tag -a v0.6.12 -m "Yo v0.6.12 — unified version source for Codex and Yo"
git push origin main --tags
───────────────────────────────
Awaiting operator review and manual publish approval.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T21:28:36.703786
🧠 Version: 0.6.0.0
⚙️ Executor: Codex
👤 Operator: Sean Gray
📍 Working Directory: /Users/seansgravy/GitHub/Yo
📁 Scan Path: /Users/seansgravy/GitHub/Yo/tasks/active
🧩 Task: codex-task-card-v0.6.12.md
⏱ Duration: 0.0s

📄 Files Created: none
✏️ Files Modified: none
🗑️ Files Deleted: none
🔁 Files Renamed/Moved: none

🧪 Tests: not run
📊 Metrics: n/a
🔖 Commit/Tag: pending

📘 Notes: Task completed successfully.
