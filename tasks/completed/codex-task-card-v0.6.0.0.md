# Codex Task Card — v0.6.0.0 — Initialize Task Lifecycle Framework

---
id: v0.6.0.0
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
Establish the foundation for Codex’s new **Human-in-the-Loop Task Lifecycle System**, including directory setup, the Markdown template, and post-run echo behavior.  
This is the final manually injected CTC — all future tasks will be run from `/tasks/active/` using the single `.` command.

---

## ⚙️ Implementation Steps
1. **Create Task Directory Structure**
   ```
   /tasks/
   ├── active/
   ├── completed/
   ├── failed/
   └── templates/
   ```
   - Ensure folders are created if missing.
   - `.gitkeep` each empty directory.

2. **Add Task Runner**
   **File:** `yo/task_runner.py`
   ```python
   from pathlib import Path
   import shutil, datetime

   def run_tasks():
       active = Path("tasks/active")
       completed = Path("tasks/completed")
       failed = Path("tasks/failed")

       for card in active.glob("*.md"):
           name = card.name
           print(f"[Codex] Running {name}")
           start = datetime.datetime.utcnow().isoformat()

           try:
               content = card.read_text()
               log = (
                   f"\n---\n## 🧾 Codex Execution Log\n"
                   f"✅ Completed {start}\n"
               )
               card.write_text(content + log)
               shutil.move(card, completed / name)
               print(f"[Codex] {name} → completed")
           except Exception as e:
               shutil.move(card, failed / name)
               print(f"[Codex] {name} → failed ({e})")
   ```

3. **Store the Template**
   **File:** `/tasks/templates/codex-task-card-template.md`  
   Use the full template you and Logos finalized.

4. **Add Post-Run Echo Behavior**
   After successful execution, Codex should print:
   ```
   ✅ Codex build complete — Yo current version: [version]
   🗂️ Task archived → /tasks/completed/[filename]
   📄 Results appended.
   ───────────────────────────────
   Manual Publish Commands:
   git add -A
   git commit -m "[commit message]"
   git tag -a [version] -m "[tag message]"
   git push origin main --tags
   ───────────────────────────────
   Please run these commands to publish to the repository.
   ```

5. **README.md Update**
   Add a new section titled **“Codex Task Lifecycle”**:
   ```markdown
   ## Codex Task Lifecycle
   After v0.6.0.0, new tasks are dropped into `/tasks/active/`.
   Run `.` in VS Code or Atlas to trigger Codex to scan, execute, append results, and move tasks automatically.
   ```

6. **Validation**
   ```bash
   python3 -m yo.task_runner
   ```
   Confirm that processed cards move to `/tasks/completed/`.

---

## 🧪 Tests
**File:** `tests/test_task_runner.py`
```python
def test_run_tasks_moves_and_logs(tmp_path):
    from yo.task_runner import run_tasks
    (tmp_path / "tasks/active").mkdir(parents=True)
    card = tmp_path / "tasks/active/test.md"
    card.write_text("# test card")
    run_tasks()
    assert not card.exists()
```

---

## 🧾 Commit Message
```
release: v0.6.0.0 — initialize Codex task lifecycle framework and template system
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.6.0.0 — initialize Codex task lifecycle framework and template system"
git tag -a v0.6.0.0 -m "Yo v0.6.0.0 — bootstrap Codex task lifecycle framework"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.6.0.0
🗂️ Task lifecycle directories created.
📄 Template stored at /tasks/templates/codex-task-card-template.md
🧠 Task runner available as yo.task_runner
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.0.0 — initialize Codex task lifecycle framework and template system"
git tag -a v0.6.0.0 -m "Yo v0.6.0.0 — bootstrap Codex task lifecycle framework"
git push origin main --tags
───────────────────────────────
Please run these commands to publish to the repository.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T15:17:57.816687
