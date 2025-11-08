> ❗ Superseded: The correct active card is /tasks/active/codex-task-card-v0.7.2.md
# Codex Task Card — v0.7.2 — Task Sanity Check & Challenge Logic

---
id: v0.7.2
status: superseded
priority: high
author: Sean Gray
assistant: Copilot
executor: Codex
reviewer: Sean Gray
created: 2025-11-08
target: main
---

## 🎯 Objective
Introduce a **sanity check and challenge phase** before Codex executes any task card.  
Codex should analyze each task card’s logic and verify feasibility, version alignment, and dependency consistency.  
If issues are found, Codex must *pause execution*, summarize the concern, and propose corrections for operator approval.

---

## ⚙️ Implementation Steps

### 1️⃣ Add Pre-Execution Validation
**File:** `yo/hooks/codex_sanity.py`
```python
from yo.utils.version import get_yo_version
from pathlib import Path
import re

def sanity_check(card_path: Path) -> dict:
    text = card_path.read_text(encoding="utf-8")
    version = get_yo_version()

    issues = []
    if f"Version: {version}" not in text and f"v{version}" not in text:
        issues.append(f"⚠️ Mismatch: Card does not mention current version ({version}).")

    if "Objective" not in text:
        issues.append("⚠️ Missing Objective section.")
    if "Implementation Steps" not in text:
        issues.append("⚠️ Missing Implementation Steps section.")

    result = {"ok": not issues, "issues": issues}
    return result
```

---

### 2️⃣ Integrate Sanity Hook into Lifecycle
In Codex’s lifecycle controller (pre-run):
```python
from yo.hooks.codex_sanity import sanity_check

result = sanity_check(card_path)
if not result["ok"]:
    print("[Codex] 🚫 Sanity check failed.")
    for i, issue in enumerate(result["issues"], 1):
        print(f"  {i}. {issue}")
    print("[Codex] ⏸ Execution paused pending operator review.")
    return
```

---

### 3️⃣ Challenge Phase
If sanity passes, Codex should print:
```
[Codex] ✅ Sanity check passed — no critical issues found.
[Codex] ⚙️ Beginning execution...
```
If it fails, Codex pauses and appends a warning block:
```
## ⚠️ Sanity Challenge
Codex identified the following issues before execution:
1. ...
2. ...
Operator must approve or modify this task card before re-run.
```

---

### 4️⃣ Documentation
Add to `docs/DEVELOPER_GUIDE.md`:
```markdown
### Sanity Check & Challenge (v0.7.2+)
Codex validates all task cards before execution. Any detected mismatch or missing section triggers a pause and appends a challenge note. The operator may modify and re-run the card.
```

---

### 5️⃣ Validation
- Test a well-formed card → passes automatically.
- Test a malformed card → triggers Codex’s “pause” message.
- Confirm that `/tasks/completed/` card includes a “Sanity Challenge” block when validation fails.

---

## 🧾 Commit Message
```
release: v0.7.2 — add Codex task sanity check and challenge logic
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.7.2 — add Codex task sanity check and challenge logic"
git tag -a v0.7.2 -m "Yo v0.7.2 — task sanity check and challenge logic"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — version: 0.7.2
🧠 Sanity check hook active
🚦 Codex will challenge inconsistent task cards before execution
───────────────────────────────
Manual Publish Commands above ready for operator approval.
```

---
## 🧾 Codex Execution Log
✅ Pending execution — v0.7.2 will enable Codex sanity validation before lifecycle execution.
```
# Codex Task Card — v0.7.2 — Task Sanity Check & Challenge Logic

---
id: v0.7.2
status: active
priority: high
author: Sean Gray
assistant: Copilot
executor: Codex
reviewer: Sean Gray
created: 2025-11-08
target: main
---

## 🎯 Objective
Introduce a **sanity check and challenge phase** before Codex executes any task card.  
Codex should analyze each task card’s logic and verify feasibility, version alignment, and dependency consistency.  
If issues are found, Codex must *pause execution*, summarize the concern, and propose corrections for operator approval.

---

## ⚙️ Implementation Steps

### 1️⃣ Add Pre-Execution Validation
**File:** `yo/hooks/codex_sanity.py`
```python
from yo.utils.version import get_yo_version
from pathlib import Path
import re

def sanity_check(card_path: Path) -> dict:
    text = card_path.read_text(encoding="utf-8")
    version = get_yo_version()

    issues = []
    if f"Version: {version}" not in text and f"v{version}" not in text:
        issues.append(f"⚠️ Mismatch: Card does not mention current version ({version}).")

    if "Objective" not in text:
        issues.append("⚠️ Missing Objective section.")
    if "Implementation Steps" not in text:
        issues.append("⚠️ Missing Implementation Steps section.")

    result = {"ok": not issues, "issues": issues}
    return result
```

---

### 2️⃣ Integrate Sanity Hook into Lifecycle
In Codex’s lifecycle controller (pre-run):
```python
from yo.hooks.codex_sanity import sanity_check

result = sanity_check(card_path)
if not result["ok"]:
    print("[Codex] 🚫 Sanity check failed.")
    for i, issue in enumerate(result["issues"], 1):
        print(f"  {i}. {issue}")
    print("[Codex] ⏸ Execution paused pending operator review.")
    return
```

---

### 3️⃣ Challenge Phase
If sanity passes, Codex should print:
```
[Codex] ✅ Sanity check passed — no critical issues found.
[Codex] ⚙️ Beginning execution...
```
If it fails, Codex pauses and appends a warning block:
```
## ⚠️ Sanity Challenge
Codex identified the following issues before execution:
1. ...
2. ...
Operator must approve or modify this task card before re-run.
```

---

### 4️⃣ Documentation
Add to `docs/DEVELOPER_GUIDE.md`:
```markdown
### Sanity Check & Challenge (v0.7.2+)
Codex validates all task cards before execution. Any detected mismatch or missing section triggers a pause and appends a challenge note. The operator may modify and re-run the card.
```

---

### 5️⃣ Validation
- Test a well-formed card → passes automatically.
- Test a malformed card → triggers Codex’s “pause” message.
- Confirm that `/tasks/completed/` card includes a “Sanity Challenge” block when validation fails.

---

## 🧾 Commit Message
```
release: v0.7.2 — add Codex task sanity check and challenge logic
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.7.2 — add Codex task sanity check and challenge logic"
git tag -a v0.7.2 -m "Yo v0.7.2 — task sanity check and challenge logic"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — version: 0.7.2
🧠 Sanity check hook active
🚦 Codex will challenge inconsistent task cards before execution
───────────────────────────────
Manual Publish Commands above ready for operator approval.
```

---
## 🧾 Codex Execution Log
✅ Pending execution — v0.7.2 will enable Codex sanity validation before lifecycle execution.
```
