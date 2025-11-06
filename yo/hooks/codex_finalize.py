"""Finalize hook for Codex structured task logging."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict

from yo.utils.logging import append_codex_log
from yo import __version__


def finalize_task(card_path: Path, context: Dict) -> Dict:
    """Finalize Codex execution with structured log validation."""

    context = dict(context)
    context["version"] = __version__
    context.setdefault("timestamp", datetime.utcnow().isoformat())

    append_codex_log(card_path, context)

    with card_path.open("r", encoding="utf-8") as handle:
        content = handle.read()

    required_tokens = ["🧠 Version:", "📘 Notes:", "⚙️ Executor:"]
    missing = [token for token in required_tokens if token not in content]

    if missing:
        print(f"[Codex] ⚠️ Warning: Missing metadata keys in append → {missing}")
        context["validation_status"] = "incomplete"
    else:
        context["validation_status"] = "valid"

    return context
