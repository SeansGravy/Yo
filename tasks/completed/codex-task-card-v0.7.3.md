# Codex Task Card — v0.7.4 — Visual Telemetry Dashboard & Metrics Overlay

---
id: v0.7.4
status: active
priority: high
author: Sean Gray
assistant: Logos
executor: Codex
reviewer: Sean Gray
created: 2025-11-08T13:00:00.000000
target: main
---

## 🎯 Objective
Implement a **Visual Telemetry Dashboard** and **Metrics Overlay** to visualize real-time Codex operations, Ollama stream health, and lane lifecycle performance.
This release introduces a lightweight web dashboard served locally with live updates from the `data/logs/metrics.jsonl` and `yo/metrics.py` telemetry stream.

---

## ⚙️ Implementation Steps

### 1️⃣ Dashboard Scaffold
**File:** `yo/telemetry/dashboard.py`
```python
from flask import Flask, render_template, jsonify
import json, time, threading

app = Flask(__name__)
METRICS_FILE = "data/logs/metrics.jsonl"

def read_metrics():
    data = []
    try:
        with open(METRICS_FILE, "r") as f:
            for line in f.readlines()[-50:]:
                data.append(json.loads(line))
    except Exception as e:
        data.append({"error": str(e)})
    return data

@app.route("/api/metrics")
def api_metrics():
    return jsonify(read_metrics())

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5059, debug=True)
```

---

### 2️⃣ Web Overlay (Frontend)
**File:** `templates/index.html`
```html
<!DOCTYPE html>
<html>
<head>
<title>Yo Telemetry Dashboard</title>
<meta http-equiv="refresh" content="3">
<style>
body { font-family: monospace; background-color: #0e0e0e; color: #00ff9d; }
h1 { color: #00ffaa; }
.log { white-space: pre-wrap; }
</style>
</head>
<body>
<h1>Yo Telemetry Dashboard — v0.7.4</h1>
<div class="log">
  {% for entry in metrics %}
    {{ entry.timestamp }} — {{ entry.message }}<br>
  {% endfor %}
</div>
</body>
</html>
```

---

### 3️⃣ Metrics Hook Integration
Extend `yo/metrics.py`:
```python
def log_metric(event, value=None, tags=None):
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": event,
        "value": value,
        "tags": tags or []
    }
    with open("data/logs/metrics.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
```
Ensure Codex lanes A–F use `log_metric()` during key transitions for real-time visibility.

---

### 4️⃣ Overlay Trigger Command
Add new CLI command in `yo/cli.py`:
```python
@click.command("telemetry")
def telemetry():
    """Launch the Yo visual telemetry dashboard."""
    os.system("python3 yo/telemetry/dashboard.py")
```

---

### 5️⃣ Structured Append Expansion
Extend structured append schema in `yo/utils/logging.append_codex_log`:
- `"dashboard_active"` → bool
- `"telemetry_events"` → int (recent log count)

---

## 🧪 Tests (Manual)
1. Run:
   ```bash
   python3 yo/telemetry/dashboard.py
   ```
2. Open `http://127.0.0.1:5059` in browser.
3. Confirm real-time updates appear as new entries are logged.
4. Run `yo telemetry` CLI command and verify dashboard autostart.
5. Confirm Codex reports:
   ```
   [Codex] Telemetry dashboard active on port 5059
   ```

---

## 🧾 Commit Message
```
release: v0.7.4 — implement visual telemetry dashboard & metrics overlay
```

## 🪜 Manual Publish Commands
```bash
git add -A
git commit -m "release: v0.7.4 — implement visual telemetry dashboard & metrics overlay"
git tag -a v0.7.4 -m "Yo v0.7.4 — implement visual telemetry dashboard & metrics overlay"
git push origin main --tags
```

---

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.7.4
🧠 Visual telemetry dashboard active
📊 Metrics overlay streaming live (data/logs/metrics.jsonl)
🚦 Lane metrics integrated
───────────────────────────────
Manual Publish Commands:
git add -A
git commit -m "release: v0.7.4 — implement visual telemetry dashboard & metrics overlay"
git tag -a v0.7.4 -m "Yo v0.7.4 — implement visual telemetry dashboard & metrics overlay"
git push origin main --tags
───────────────────────────────
Awaiting operator review and manual publish approval.
```

---
## 🧾 Codex Execution Log
✅ Pending execution — v0.7.4 will activate the visual telemetry layer and integrate real-time lifecycle reporting.
```

---

# Codex Task Card — v0.7.3 — Multi-Lane Lifecycle & Sanity Audit

---
id: v0.7.3
status: completed
priority: critical
author: Sean Gray
assistant: Copilot
executor: Codex
reviewer: Sean Gray
created: 2025-11-08T12:40:39.440281
target: main
---

## 🎯 Objective
Activate Codex’s **six-lane lifecycle** (A–F) with built‑in **sanity audit** and **structured logging**.
Each lane reports readiness, execution status, and summary to the card’s structured-append section.

**Lanes**
- **A — Core Runtime** (`yo/*.py`)
- **B — Telemetry** (`yo/metrics.py`)
- **C — Documentation** (`docs/*.md`)
- **D — Testing** (`tests/*.py`)
- **E — Cleanup** (shell scripts, workflows)
- **F — Experience** (CLI, UX, structured append)

---

## ⚙️ Implementation Steps

### 1️⃣ Lifecycle Map
**File:** `yo/hooks/codex_lifecycle.py`
```python
LANES = [
    ("A", "Core Runtime", "yo/*.py"),
    ("B", "Telemetry", "yo/metrics.py"),
    ("C", "Documentation", "docs/*.md"),
    ("D", "Testing", "tests/*.py"),
    ("E", "Cleanup", "shell scripts, workflows"),
    ("F", "Experience", "CLI, Codex UX, structured append"),
]

def initialize_lifecycle():
    print("[Codex] Initializing six-lane lifecycle...")
    for lane, name, scope in LANES:
        print(f"[Codex] Lane {lane}: {name} → scope: {scope}")
    print("[Codex] Lifecycle initialization complete.")
```

### 2️⃣ Sanity Audit
Validate lane scopes before execution:
```python
def sanity_audit():
    issues = []
    for lane, name, scope in LANES:
        if not scope:
            issues.append(f"Lane {lane} missing scope.")
    return issues
```
If issues exist:
```
[Codex] 🚫 Sanity audit failed:
  1. Lane X missing scope
```
and the card gets a **Sanity Challenge** block.

### 3️⃣ Per-Lane Result Tracking
Record completion and print a compact summary:
```
## 🧩 Track Summary
A: ✅ Core  | B: ✅ Telemetry | C: ✅ Docs
D: ✅ Tests | E: ✅ Cleanup   | F: ✅ Experience
```

### 4️⃣ Structured Append Expansion
Extend `yo/utils/logging.append_codex_log` keys:
- `lanes` → dict of lane → status
- `audit_passed` → bool
- `issues` → list

### 5️⃣ Developer Guide Note
Append to `docs/DEVELOPER_GUIDE.md`:
```markdown
### Six-Lane Lifecycle (v0.7.3+)
Codex executes all development areas (A–F) in conceptual lanes and logs lane/audit results to the task card.
```

---

## 🧪 Tests (Manual)
1. Place this card in `/tasks/active/` and trigger Codex.
2. Confirm audit passes and lifecycle prints:
```
[Codex] Initializing six-lane lifecycle...
[Codex] ✅ All lanes verified
[Codex] Running lifecycle execution...
```
3. Verify the card moved to `/tasks/completed/` with a **Track Summary** block appended.

---

## 🧾 Commit Message
```
release: v0.7.3 — implement multi-lane lifecycle and sanity audit
```

## ✅ Expected Codex Echo
```
✅ Codex build complete — Yo current version: 0.7.3
🧠 Six-lane lifecycle active
🚦 Sanity audit verified — all lanes reachable
📘 Structured append includes per-lane summary
```
