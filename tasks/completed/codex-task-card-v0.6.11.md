# Codex Task Card — v0.6.11 — Bind Finalize Hook, Validate Append Before Archive

---
id: v0.6.11
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
Fully bind the structured append logic (`finalize_task`) into Codex’s run cycle and remove the legacy timestamp-only log writer.  
Codex should now **verify that the structured log exists and passes validation before moving the card to `/tasks/completed/`.**

---

## ⚙️ Implementation Steps  

### 1️⃣ Remove the legacy one-liner append  
Search for the old static line (likely in Codex’s `run_task()` or finalizer):  
```python
card.write_text(content + "\n---\n## 🧾 Codex Execution Log\n✅ Completed {timestamp}\n")
```  
Delete it entirely.

---

### 2️⃣ Bind finalize hook directly in the runtime  
Replace that line with the structured finalize call:  
```python
from yo.hooks.codex_finalize import finalize_task
context = finalize_task(card_path, codex_context)
print(f"[Codex] Append validation: {context['validation_status']}")
```

---

### 3️⃣ Add pre-archive validation  
Immediately before the move step, confirm the append actually happened:  
```python
with card_path.open("r", encoding="utf-8") as f:
    content = f.read()

if "🧠 Version:" not in content or "📘 Notes:" not in content:
    print("[Codex] ⚠️ Structured append missing, skipping archive.")
    return
else:
    print("[Codex] ✅ Structured append detected, proceeding to archive.")
    move_to_completed(card_path)
```

---

### 4️⃣ Add self-test for structured append  
Create `/tests/test_append_validation.py` to simulate Codex’s post-run behavior:  
```python
from yo.hooks.codex_finalize import finalize_task
from pathlib import Path

def test_append_validation(tmp_path):
    card = tmp_path / "card.md"
    card.write_text("# test")
    context = {"operator": "Sean Gray", "cwd": str(tmp_path)}
    finalize_task(card, context)
    data = card.read_text()
    assert "🧠 Version:" in data
    assert "📘 Notes:" in data
```

---

### 5️⃣ Developer Guide update  
Append to `docs/DEVELOPER_GUIDE.md`:  
```markdown
### Validation Enforcement (v0.6.11+)
Codex now refuses to archive a task card if the structured log
block is missing or incomplete. Legacy timestamp append behavior
is fully deprecated.
```

---

## 🧪 Tests (Manual)  
1. Place this card into `/tasks/active/`.  
2. Run `.`  
3. Confirm the console shows:  
   ```
   [Codex] Append validation: valid
   [Codex] ✅ Structured append detected, proceeding to archive.
   ```  
4. Inspect `/tasks/completed/codex-task-card-v0.6.11.md`; it should contain full metadata.

---

## 🧾 Commit Message  
```
release: v0.6.11 — bind finalize hook and enforce structured append validation before archive
```

---

## 🪜 Manual Publish Commands  
```bash
git add -A
git commit -m "release: v0.6.11 — bind finalize hook and enforce structured append validation before archive"
git tag -a v0.6.11 -m "Yo v0.6.11 — finalize hook and append validation"
git push origin main --tags
```

---

## ✅ Expected Codex Echo  
```
✅ Codex build complete — Yo current version: 0.6.11
🧠 finalize_task hook active
⚙️ Validation: all metadata present
📘 Structured append confirmed; archived successfully
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.6.11 — bind finalize hook and enforce structured append validation before archive"
git tag -a v0.6.11 -m "Yo v0.6.11 — finalize hook and append validation"
git push origin main --tags
───────────────────────────────
Awaiting operator review and manual publish approval.
```

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-06T20:17:29.773252
