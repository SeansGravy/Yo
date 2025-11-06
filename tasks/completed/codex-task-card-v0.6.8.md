# Codex Task Card — v0.6.8 — Remove Task Runner, Fix Version Source, Restore Native Logging

---
id: v0.6.8
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
Eliminate the redundant **task runner** and restore Codex’s **native direct execution pipeline** for task cards.  
Fix version propagation to use the single source in `yo/__init__.py` and re-enable proper verbose append behavior.

---

## ⚙️ Implementation Steps

### 1️⃣ Remove `yo/task_runner.py` and its references
- Delete the file `yo/task_runner.py`.
- Remove any import, alias, or CLI reference to it in:
  - `yo/__init__.py`
  - `yo/cli.py`
  - `.github/workflows/*`
  - any automation or documentation.

Codex will now read and execute Markdown cards **directly** from `/tasks/active/` without wrapping logic.

### 2️⃣ Fix version source and printout
- Ensure all components pull the version from a single source:
  **File:** `yo/__init__.py`
  ```python
  __version__ = "0.6.8"
  ```
- In all CLI and UI layers:
  ```python
  from yo import __version__
  print(f"🧠 Yo v{__version__}")
  ```
- Remove any constants like:
  ```python
  YO_VERSION = "0.3.8"
  ```

### 3️⃣ Restore Codex’s native verbose logging
Once the runner layer is removed:
- Codex will directly handle task reads/writes.
- All console output, diff collection, and test reporting will be correctly appended again.
- Verify that `/tasks/completed/codex-task-card-v0.6.8.md` contains the full structured metadata log from v0.6.7’s schema.

### 4️⃣ Documentation Update
Append to `docs/DEVELOPER_GUIDE.md` under “Maintenance Policy”:
```markdown
## Runner Deprecation
As of v0.6.8, the legacy Python task runner has been retired.
Codex natively executes and logs all task cards.
All version strings derive exclusively from yo/__init__.py.
```

### 5️⃣ Verification
1. Place this card into `/tasks/active/`
2. Run `.`
3. Verify:
   - No mention of `task_runner` in logs.
   - Codex’s append contains full metadata and diff fields.
   - CLI output header shows:
     ```
     🧠 Yo v0.6.8 | Namespace: default | Health: 100 | Pass Rate: 100%
     ```

---

## 🧪 Tests (Manual)
- Confirm that `/yo/task_runner.py` no longer exists.
- Confirm that running `yo version` returns `0.6.8`.
- Confirm that Codex appends full logs including scan path, test summary, and file changes.

---

## 🧾 Commit Message
```
release: v0.6.8 — remove Python task runner, fix version propagation, restore native Codex logging
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.6.8 — remove Python task runner, fix version propagation, restore native Codex logging"
git tag -a v0.6.8 -m "Yo v0.6.8 — removed task runner and fixed version source"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.6.8
🧠 Version source unified via yo/__init__.py
🧾 Task runner removed — using native Codex execution
📘 Full verbose log appended with file diff and test summary
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.8 — remove Python task runner, fix version propagation, restore native Codex logging"
git tag -a v0.6.8 -m "Yo v0.6.8 — removed task runner and fixed version source"
git push origin main --tags
───────────────────────────────
Awaiting operator review and manual publish approval.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T19:51:09.328944
