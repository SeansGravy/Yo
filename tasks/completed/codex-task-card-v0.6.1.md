# Codex Task Card — v0.6.1 — Activate Task Workflow Protocol

---
id: v0.6.1
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
Activate the new Human‑in‑the‑Loop task workflow.  Codex will scan `/tasks/active/` when triggered, execute each Markdown task card once, append a result log, and move it to `/tasks/completed/` (or `/tasks/failed/` if execution errors).  Codex must also print manual publish commands for the operator to commit and tag the results.

---

## 🧩 Behaviour Definition

1. **Trigger:**  
   - When the operator types a single dot (`.`) or says “scan for tasks”, Codex performs a one‑time scan of `/tasks/active/`.  
   - Codex does not watch continuously.

2. **Scanning:**  
   - Codex reads every `.md` file in `/tasks/active/`, sorted alphabetically.  
   - It processes each card sequentially.

3. **Execution:**  
   - Codex executes the “Implementation Steps” described in the card.  
   - It captures stdout, test results, and commit information.  
   - It appends an execution log to the end of the same file, e.g.:

     ```markdown
     ---
     ## 🧾 Codex Execution Log
     ✅ Completed 2025‑11‑06T18:00Z
     🧠 Version: v0.6.1
     🧪 Tests: all passed
     🔖 Commit: abc1234 (main)
     ```

4. **Archival:**  
   - On success, move the card to `/tasks/completed/`.  
   - On failure, move it to `/tasks/failed/`.  
   - Do not modify files in `/tasks/active/` except moving them after execution.

5. **Console Output:**  
   - After processing each card, print a summary line:

     ```
     [Codex] v0.6.1 — success → /tasks/completed/
     ```

   - After processing all cards, print:

     ```
     ✅ Codex scan complete
     🗂️  [number] tasks processed (completed: X, failed: Y)
     ───────────────────────────────
     Manual Publish Commands:
     git add -A
     git commit -m "release: batch completion"
     git tag -a v0.6.1 -m "Yo v0.6.1 — batch run"
     git push origin main --tags
     ───────────────────────────────
     Please run these commands to publish to the repository.
     ```

6. **No internal task runner:**  
   - Codex should not create or rely on a Python script inside `yo/`.  
   - All logic resides inside Codex; tasks remain pure Markdown specs.

7. **Read‑only Yo system:**  
   - This workflow is external to Yo.  It does not modify application behaviour.

---

## 🧪 Tests
No code changes to Yo; therefore, no new unit tests are required.  Manual verification is sufficient.

---

## 🧾 Commit Message
```
release: v0.6.1 — activate Codex task workflow protocol
```

---

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.6.1 — activate Codex task workflow protocol"
git tag -a v0.6.1 -m "Yo v0.6.1 — activated Codex task workflow protocol"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.6.1
🔘 Dot trigger active
🗂️ Tasks auto-scanned and archived
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.1 — activate Codex task workflow protocol"
git tag -a v0.6.1 -m "Yo v0.6.1 — activated Codex task workflow protocol"
git push origin main --tags
───────────────────────────────
Please run these commands to publish to the repository.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T16:26:43.983117
