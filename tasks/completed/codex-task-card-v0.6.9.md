# Codex Task Card — v0.6.9 — Replace Legacy Append Logic with Full Structured Write

---
id: v0.6.9
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
Replace the legacy static append logic that only writes "✅ Completed {timestamp}" with a **dynamic, structured append system** that logs full execution metadata to the completed task card.

---

## ⚙️ Implementation Steps

### 1️⃣ Locate the append handler
- The one-liner append currently lives in either:
  ```
  yo/task_runner.py
  ```
  or Codex’s internal completion callback (search for "Codex Execution Log" or "✅ Completed").
- Replace that section with a structured block generator function.

### 2️⃣ Create a new helper: `append_codex_log(context: dict)`
**File:** `yo/utils/logging.py`
```python
from datetime import datetime
from pathlib import Path
import json

def append_codex_log(card_path: Path, context: dict):
    """Append structured Codex execution context to the task card."""
    timestamp = datetime.utcnow().isoformat()
    section = f"""
---
## 🧾 Codex Execution Log
✅ Completed {timestamp}
🧠 Version: {context.get('version', 'unknown')}
⚙️ Executor: Codex
👤 Operator: {context.get('operator', 'Sean Gray')}
📍 Working Directory: {context.get('cwd', 'unknown')}
📁 Scan Path: {context.get('scan_path', 'unknown')}
🧩 Task: {card_path.name}
⏱ Duration: {context.get('duration', 'unknown')}s

📄 Files Created: {', '.join(context.get('created', ['none']))}
✏️ Files Modified: {', '.join(context.get('modified', ['none']))}
🗑️ Files Deleted: {', '.join(context.get('deleted', ['none']))}
🔁 Files Renamed/Moved: {', '.join(context.get('renamed', ['none']))}

🧪 Tests: {context.get('tests', 'none')}
📊 Metrics: {context.get('metrics', 'none')}
🔖 Commit/Tag: {context.get('commit', 'none')}

📘 Notes: {context.get('notes', 'Task completed successfully.')}
"""
    with card_path.open("a", encoding="utf-8") as f:
        f.write(section)
```

### 3️⃣ Populate `context` dictionary dynamically
Where Codex finishes a task:
```python
context = {
    "version": __version__,
    "cwd": str(Path.cwd()),
    "scan_path": "/tasks/active/",
    "duration": elapsed_seconds,
    "created": created_files,
    "modified": modified_files,
    "deleted": deleted_files,
    "renamed": renamed_files,
    "tests": test_summary,
    "metrics": f"Health {health}%, Pass Rate {pass_rate}%",
    "commit": current_commit,
    "notes": summary,
}
append_codex_log(card_path, context)
```

### 4️⃣ Ensure console and append match
When Codex echoes its summary to the terminal, it should read directly from the same context dict, so both append and console output match 1:1.

### 5️⃣ Validation
After running:
- `/tasks/completed/codex-task-card-v0.6.9.md` should contain **at least 10 structured lines**.
- The last block should match the runtime console output.

---

## 🧪 Tests (Manual)
1. Place this card into `/tasks/active/`.
2. Run `.`  
3. Check that the appended block matches the expected structured format.  
4. Confirm version and metrics fields populate correctly.

---

## 🧾 Commit Message
```
release: v0.6.9 — replace legacy append logic with structured write for full Codex context logging
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.6.9 — replace legacy append logic with structured write for full Codex context logging"
git tag -a v0.6.9 -m "Yo v0.6.9 — replaced legacy append logic with structured write"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.6.9
📘 Structured append logging active
🧠 Executor: Codex | Operator: Sean Gray
📄 created: 2 | ✏️ modified: 3 | 🗑️ deleted: 0 | 🔁 renamed: 0
🧪 28 passed, 0 failed, 1 skipped
📘 Appended detailed log to /tasks/completed/codex-task-card-v0.6.9.md
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.9 — replace legacy append logic with structured write for full Codex context logging"
git tag -a v0.6.9 -m "Yo v0.6.9 — replaced legacy append logic with structured write"
git push origin main --tags
───────────────────────────────
Awaiting operator review and manual publish approval.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T19:57:35.841123
