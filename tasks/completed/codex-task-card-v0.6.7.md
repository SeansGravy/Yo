# Codex Task Card — v0.6.7 — Verbose Append (Diff, Tests, Context) & Scan Path Echo

---
id: v0.6.7
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
Ensure the appended **Codex Execution Log** is fully informative — not just a timestamp.  
Codex must capture and append: **scan path, working directory, version, elapsed time, commands/tests run, and a precise list of files created/modified/moved/deleted** — so the operator can compare intent vs. outcome before publishing.

---

## ⚙️ Implementation Steps

### 1) Echo scan path & working directory
- At the start of a task run, print and later append:
  - **Scan Path:** absolute path Codex used to find cards (must be `/tasks/active/` under repo root).
  - **Working Directory (cwd):** absolute repo root Codex ran from.
  - **Yo Version:** import from `yo.__init__.__version__`.

Example console:
```
[Codex] Scan path: /Users/seansgravy/GitHub/Yo/tasks/active
[Codex] Working directory: /Users/seansgravy/GitHub/Yo
[Codex] Yo version: 0.6.7
```

### 2) Capture pre‑snapshot (baseline)
Before running Implementation Steps:
- `git rev-parse --short HEAD` → `base_commit`
- `git status --porcelain=v1 -z` → baseline status map
- `date -u +%Y-%m-%dT%H:%M:%SZ` → start timestamp

### 3) Execute steps with verbose logging
- For each step, echo the exact command(s) and capture stdout/stderr.
- If using pytest, capture the final summary line (e.g., `28 passed, 0 failed, 1 skipped in 8.23s`).

### 4) Capture post‑snapshot (changes)
After steps complete:
- `git status --porcelain=v1 -z` → new status
- Derive and list by category:
  - **Created (A??)**  
  - **Modified ( M)**  
  - **Deleted ( D)**  
  - **Renamed (R )** (show `old → new` if available)  
  - **Moved Task Card:** `/tasks/active/<file>.md → /tasks/completed/<file>.md` or `/tasks/failed/`
- `git rev-parse --short HEAD` → `end_commit`
- `date -u +%Y-%m-%dT%H:%M:%SZ` → end timestamp
- Compute elapsed seconds.

If no tracked file changes are detected, set each list to `"none"` and append:
```
No tracked file modifications detected for this task.
```

### 5) Append a structured execution block
Append the following to the processed task card (always include all fields):

```markdown
---
## 🧾 Codex Execution Log
✅ Completed {END_ISO}
🧠 Version: {YO_VERSION}
⚙️ Executor: Codex
👤 Operator: Sean Gray
📍 Scan Path: {SCAN_PATH}
📁 Working Directory: {CWD}
🧩 Task: {TASK_FILENAME}
⏱ Duration: {ELAPSED_SECONDS}s

📄 Files Created: {CREATED_LIST}
✏️ Files Modified: {MODIFIED_LIST}
🗑️ Files Deleted: {DELETED_LIST}
🔁 Files Renamed/Moved: {RENAMED_LIST}
📂 Task Card Move: {TASK_MOVE}  # e.g., tasks/active/foo.md → tasks/completed/foo.md

🧪 Tests Summary: {TEST_SUMMARY}  # e.g., 28 passed, 0 failed, 1 skipped in 8.23s
🔖 Commits/Tags: {COMMIT_TAG_INFO}  # if any, else “none”

📘 Notes: {NOTES_OR_NONE}
```

Notes:
- Always render non-empty lists; if none, write `"none"` explicitly.
- If steps failed, write `⚠️ Completed with errors` instead of ✅ and include exception summary lines.

### 6) Console summary must match appended content
After moving the card, echo a compact summary **that mirrors the appended fields**, including test summary and change counts.

Example console end:
```
✅ v0.6.7 completed — Yo 0.6.7
📄 created: 1 | ✏️ modified: 2 | 🗑️ deleted: 0 | 🔁 renamed: 0
🧪 28 passed, 0 failed, 1 skipped
📘 Appended verbose log to: tasks/completed/codex-task-card-v0.6.7.md
Awaiting operator review and manual publish approval.
```

---

## 🧪 Tests (Manual)
1. Place this card into `/tasks/active/` and run `.`  
2. Confirm console shows **Scan Path**, **Working Directory**, **Yo version**, and a **full end summary**.  
3. Open `/tasks/completed/codex-task-card-v0.6.7.md` and verify the appended block contains **all fields** with explicit `"none"` for empty lists.

---

## 🧾 Commit Message
```
release: v0.6.7 — verbose append with diff, test summary, and execution context
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.6.7 — verbose append with diff, test summary, and execution context"
git tag -a v0.6.7 -m "Yo v0.6.7 — verbose append, diff, and execution context"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.6.7
📍 Scan Path: /.../tasks/active | CWD: /.../Yo
📄 created: N | ✏️ modified: M | 🗑️ deleted: D | 🔁 renamed: R
🧪 {TEST_SUMMARY}
📘 Appended verbose log → tasks/completed/codex-task-card-v0.6.7.md
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.7 — verbose append with diff, test summary, and execution context"
git tag -a v0.6.7 -m "Yo v0.6.7 — verbose append, diff, and execution context"
git push origin main --tags
───────────────────────────────
Awaiting operator review and manual publish approval.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T19:42:10.256769
