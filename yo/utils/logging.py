"""Structured logging utilities for Codex task lifecycle."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable


def append_codex_log(card_path: Path, context: Dict) -> None:
    """Append structured Codex execution context to the task card."""

    timestamp = context.get("timestamp") or datetime.utcnow().isoformat()

    def _fmt_list(values: Iterable[str]) -> str:
        values = list(values or [])
        return ", ".join(values) if values else "none"

    section = f"""
---
## 🧾 Codex Execution Log
✅ Completed {timestamp}
🧠 Version: {context.get('version', 'unknown')}
⚙️ Executor: Codex
👤 Operator: {context.get('operator', 'unknown')}
📍 Working Directory: {context.get('cwd', 'unknown')}
📁 Scan Path: {context.get('scan_path', 'unknown')}
🧩 Task: {card_path.name}
⏱ Duration: {context.get('duration', 'unknown')}s

📄 Files Created: {_fmt_list(context.get('created', []))}
✏️ Files Modified: {_fmt_list(context.get('modified', []))}
🗑️ Files Deleted: {_fmt_list(context.get('deleted', []))}
🔁 Files Renamed/Moved: {_fmt_list(context.get('renamed', []))}

🧪 Tests: {context.get('tests', 'none')}
📊 Metrics: {context.get('metrics', 'none')}
🔖 Commit/Tag: {context.get('commit', 'none')}

📘 Notes: {context.get('notes', 'Task completed successfully.')}
"""
    with card_path.open("a", encoding="utf-8") as handle:
        handle.write(section)
