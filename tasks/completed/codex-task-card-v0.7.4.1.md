# Codex Task Card — v0.7.4.1 — Patch-Versioning & Lifecycle Sync

---
id: v0.7.4.1
status: active
priority: critical
author: Sean Gray
assistant: Logos
executor: Codex
reviewer: Sean Gray
created: 2025-11-08T14:11:00.000000
target: main
---

## Objective
Stabilize Codex lifecycle execution by adding patch-level version tracking and ensuring the six-lane lifecycle and telemetry hooks load automatically. Codex should detect lifecycle/telemetry failure and auto-increment a patch version (x.x.x.n) before retrying.

## Implementation Steps

### 1) Create yo/utils/versioning.py
```python
# yo/utils/versioning.py
import json, os

VERSION_FILE = "data/version.json"

def get_version():
    if not os.path.exists(VERSION_FILE):
        return "0.0.0.0"
    try:
        with open(VERSION_FILE, "r") as f:
            return json.load(f).get("version", "0.0.0.0")
    except Exception:
        return "0.0.0.0"

def set_version(ver: str):
    os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
    with open(VERSION_FILE, "w") as f:
        json.dump({"version": ver}, f, indent=2)
    print(f"[Codex] Version set to {ver}")

def bump_patch():
    current = get_version()
    parts = current.split(".")
    if len(parts) < 4:
        parts += ["0"] * (4 - len(parts))
    parts[-1] = str(int(parts[-1]) + 1)
    new = ".".join(parts)
    set_version(new)
    return new
```

### 2) Update yo/__init__.py
```python
from yo.utils.versioning import get_version, bump_patch
from yo.hooks.codex_lifecycle import initialize_lifecycle, sanity_audit

VERSION = get_version()

try:
    print(f"[Codex] Starting with version {VERSION}")
    initialize_lifecycle()
    sanity_audit()
except Exception as e:
    print(f"[Codex] Lifecycle/telemetry sync error: {e}")
    VERSION = bump_patch()
```

### 3) Ensure yo/hooks/codex_lifecycle.py exists
```python
LANES = [
    ("A", "Core Runtime", "yo/*.py"),
    ("B", "Telemetry", "yo/metrics.py"),
    ("C", "Documentation", "docs/*.md"),
    ("D", "Testing", "tests/*.py"),
    ("E", "Cleanup", "shell scripts, workflows"),
    ("F", "Experience", "CLI, UX, structured append"),
]

def initialize_lifecycle():
    print("[Codex] Initializing six-lane lifecycle...")
    for lane, name, scope in LANES:
        print(f"[Codex] Lane {lane}: {name} → scope: {scope}")
    print("[Codex] Lifecycle initialization complete.")

def sanity_audit():
    print("[Codex] Running sanity audit...")
    issues = []
    for lane, name, scope in LANES:
        if not scope:
            issues.append(f"Lane {lane} missing scope definition.")
    if issues:
        print("[Codex] Audit failed:")
        for issue in issues:
            print(f" - {issue}")
    else:
        print("[Codex] All lanes validated.")
    return issues
```

### 4) Docs update: docs/DEVELOPER_GUIDE.md (append)
```markdown
### Patch-Level Versioning
Codex increments patch versions (.1, .2, .3, …) automatically when lifecycle or telemetry operations fail. Each .n sub-version is an incremental stabilization step under the same minor release. Promote a new minor only when 0.7.4.x is stable.
```

## Tests (Manual)
1) Place this card in /tasks/active/ and run `.`
2) Confirm logs show lifecycle initialization and version handling.
3) Verify data/version.json contains the updated patch version.
4) Confirm yo/telemetry/dashboard.py can be launched.

## Commit Message
release: v0.7.4.1 — add patch-versioning, lifecycle/telemetry sync logic

## Expected Codex Echo
✅ Codex build complete — Yo current version: 0.7.4.1
🧠 Lifecycle and telemetry sync stable
🔁 Patch auto-increment enabled
📄 data/version.json updated

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-08T13:49:13.423327
🧠 Version: 0.6.0.0
⚙️ Executor: Codex
👤 Operator: Sean Gray
📍 Working Directory: /Users/seansgravy/GitHub/Yo
📁 Scan Path: /Users/seansgravy/GitHub/Yo/tasks/active
🧩 Task: codex-task-card-v0.7.4.1.md
⏱ Duration: 0.0s

📄 Files Created: none
✏️ Files Modified: none
🗑️ Files Deleted: none
🔁 Files Renamed/Moved: none

🧪 Tests: not run
📊 Metrics: n/a
🔖 Commit/Tag: pending

📘 Notes: Task completed successfully.
