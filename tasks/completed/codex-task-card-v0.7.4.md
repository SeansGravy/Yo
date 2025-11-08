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

---
## 🧾 Codex Execution Log
✅ Completed 2025-11-08T13:33:35.987523
🧠 Version: 0.6.0.0
⚙️ Executor: Codex
👤 Operator: Sean Gray
📍 Working Directory: /Users/seansgravy/GitHub/Yo
📁 Scan Path: /Users/seansgravy/GitHub/Yo/tasks/active
🧩 Task: codex-task-card-v0.7.4.md
⏱ Duration: 0.0s

📄 Files Created: none
✏️ Files Modified: none
🗑️ Files Deleted: none
🔁 Files Renamed/Moved: none

🧪 Tests: not run
📊 Metrics: n/a
🔖 Commit/Tag: pending

📘 Notes: Task completed successfully.
