# Codex Task Card — v0.6.5 — Task Runner Alignment & Repo Maintenance

---
id: v0.6.5
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
1. Fix Codex’s **task runner default directory** so it looks in `/tasks/active/` instead of `/tasks/`.  
2. Perform general repository cleanup — remove unused shell scripts from the repo root and confirm all references to them are safely retired.

---

## ⚙️ Implementation Steps

### 1. Task Runner Directory Alignment
- Locate Codex’s task runner or supporting logic (likely `yo/task_runner.py` or equivalent in `.codex/` or automation scripts).  
- Change the **default scan path** from:
  ```python
  Path("tasks")
  ```
  to:
  ```python
  Path("tasks/active")
  ```
- Add a safety check: if `/tasks/active/` does not exist, Codex should create it automatically and print:
  ```
  [Codex] Created missing directory: /tasks/active/
  ```

- Log the full path being scanned at startup:
  ```
  [Codex] Scanning for task cards in /tasks/active/
  ```

### 2. Repo Maintenance — Cleanup Old Shell Scripts
- Identify all `.sh` files in the top-level directory (`Yo/`) using:
  ```bash
  find . -maxdepth 1 -type f -name "*.sh"
  ```
- For each file, check if it’s referenced anywhere:
  ```bash
  grep -R "filename.sh" .
  ```
- For files not referenced by any code, test script, or doc:
  - Move them to a new archival folder:
    ```
    /archive/scripts/
    ```
  - If verified obsolete, remove them from version control with:
    ```bash
    git rm old_script.sh
    ```

### 3. Documentation Update
- Append a “Maintenance Policy” section to `docs/DEVELOPER_GUIDE.md`:
  ```markdown
  ## Maintenance Policy
  - Codex task runner defaults to /tasks/active/.
  - All obsolete or unreferenced scripts are periodically archived or deleted.
  - The /archive/ folder preserves non-critical legacy artifacts for historical reference.
  ```

### 4. Verification
- Run Codex with `.` and confirm:
  - It scans `/tasks/active/` without needing manual redirection.
  - The console log shows the correct scan path.
  - No `.sh` files remain in the repo root (unless actively used).

---

## 🧪 Tests
Manual verification for now — validate that:
- Codex reports the correct scan directory in its startup log.
- Legacy shell scripts are safely removed or archived.
- Documentation accurately reflects the new behavior.

---

## 🧾 Commit Message
```
release: v0.6.5 — fix Codex task runner path to /tasks/active and cleanup unused shell scripts
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.6.5 — fix Codex task runner path to /tasks/active and cleanup unused shell scripts"
git tag -a v0.6.5 -m "Yo v0.6.5 — corrected task runner path and performed repo cleanup"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.6.5
📂 Task runner path fixed → /tasks/active/
🧹 Cleaned up unused shell scripts from repo root
📘 Updated docs/DEVELOPER_GUIDE.md with Maintenance Policy
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.5 — fix Codex task runner path to /tasks/active and cleanup unused shell scripts"
git tag -a v0.6.5 -m "Yo v0.6.5 — corrected task runner path and performed repo cleanup"
git push origin main --tags
───────────────────────────────
Please run these commands to publish to the repository.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T19:03:37.858814
