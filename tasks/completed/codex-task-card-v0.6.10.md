# Codex Task Card — v0.6.10 — Attach Structured Append Hook and Validation

---
id: v0.6.10
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
Bind Codex’s new structured append logic (`append_codex_log`) directly to its post-execution pipeline.
Remove legacy appender calls, enforce runtime validation of appended metadata, and update documentation accordingly.

---

## ⚙️ Implementation Steps

### 1️⃣ Remove the legacy append call
Locate the simple append logic in Codex’s post-execution section (where it writes `✅ Completed {timestamp}`):
- It may reside inside:
  ```
  yo/task_runner.py  # remove if still present
  yo/cli.py
  or Codex’s internal finalize_task() event
  ```
- Delete or comment out that legacy append statement:
  ```python
  card.write_text(content + "\n---\n## 🧾 Codex Execution Log\n✅ Completed {timestamp}\n")
  ```
- Ensure no other function reintroduces that one-liner.

---

### 2️⃣ Implement the new finalize hook
Create a dedicated hook for Codex finalization:
**File:** `yo/hooks/codex_finalize.py`
```python
from yo.utils.logging import append_codex_log
from yo import __version__
from datetime import datetime
from pathlib import Path

def finalize_task(card_path: Path, context: dict):
    """Finalize Codex execution with structured log validation."""
    context["version"] = __version__
    context.setdefault("timestamp", datetime.utcnow().isoformat())

    # Append structured context
    append_codex_log(card_path, context)

    # Validation check
    with card_path.open("r", encoding="utf-8") as f:
        content = f.read()
        required = ["🧠 Version:", "📘 Notes:", "⚙️ Executor:"]
        missing = [k for k in required if k not in content]

    if missing:
        print(f"[Codex] ⚠️ Warning: Missing metadata keys in append → {missing}")
        context["validation_status"] = "incomplete"
    else:
        context["validation_status"] = "valid"

    return context
```

---

### 3️⃣ Integrate the hook into Codex’s completion handler
In the Codex engine (or wherever it marks a task as finished):
Replace any hardcoded append call with:
```python
from yo.hooks.codex_finalize import finalize_task
context = finalize_task(card_path, codex_context)
```
Ensure Codex prints the final context summary before archiving:
```python
print(f"[Codex] Append validation: {context['validation_status']}")
print(f"[Codex] Task archived to /tasks/completed/{card_path.name}")
```

---

### 4️⃣ Documentation Update
Append to `docs/DEVELOPER_GUIDE.md`:
```markdown
## Codex Post-Execution Hook (v0.6.10+)

Codex now uses a unified finalize hook for structured task logging.
This hook writes full metadata, validates key fields, and reports
missing context data before task archival.

### Required Keys
- 🧠 Version
- 📘 Notes
- ⚙️ Executor
```

---

### 5️⃣ Verification
1. Place this card into `/tasks/active/`.
2. Run `.`
3. Confirm:
   - The task completes and appends the full structured block.
   - Console output includes:
     ```
     [Codex] Append validation: valid
     [Codex] Task archived to /tasks/completed/codex-task-card-v0.6.10.md
     ```
   - The card file contains keys `🧠 Version:`, `📘 Notes:`, and `⚙️ Executor:`.

---

## 🧪 Tests (Manual)
- Verify `/yo/hooks/codex_finalize.py` exists.
- Confirm no legacy append calls remain.
- Confirm task append log includes validation keys and context data.

---

## 🧾 Commit Message
```
release: v0.6.10 — attach structured append hook with validation and finalize Codex logging pipeline
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.6.10 — attach structured append hook with validation and finalize Codex logging pipeline"
git tag -a v0.6.10 -m "Yo v0.6.10 — structured append hook with validation"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.6.10
🧠 Structured append hook active
⚙️ Validation: all metadata present
📘 /tasks/completed/codex-task-card-v0.6.10.md updated with full context
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.10 — attach structured append hook with validation and finalize Codex logging pipeline"
git tag -a v0.6.10 -m "Yo v0.6.10 — structured append hook with validation"
git push origin main --tags
───────────────────────────────
Awaiting operator review and manual publish approval.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T20:09:23.248770
