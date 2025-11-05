"""Runtime recovery utilities for Yo."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

SESSION_ROOT = Path("data/logs/sessions")
PENDING_DIR = SESSION_ROOT / "pending"
PENDING_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_type: str, session_id: str) -> Path:
    safe_type = session_type.replace("/", "_")
    return PENDING_DIR / f"{safe_type}_{session_id}.json"


def start_session(session_type: str, metadata: Dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    session_id = metadata.get("session_id") or uuid.uuid4().hex
    payload = {
        "session_id": session_id,
        "type": session_type,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "metadata": metadata,
    }
    path = _session_path(session_type, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return session_id


def update_session(session_type: str, session_id: str, metadata: Dict[str, Any]) -> None:
    path = _session_path(session_type, session_id)
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {
            "session_id": session_id,
            "type": session_type,
            "metadata": {},
        }
    payload.setdefault("metadata", {}).update(metadata)
    payload["updated_at"] = datetime.utcnow().isoformat() + "Z"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def complete_session(session_type: str, session_id: str) -> None:
    path = _session_path(session_type, session_id)
    if path.exists():
        path.unlink()


def list_pending(session_type: str | None = None) -> List[Dict[str, Any]]:
    sessions: List[Dict[str, Any]] = []
    if not PENDING_DIR.exists():
        return sessions
    for file in sorted(PENDING_DIR.glob("*.json")):
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if session_type and payload.get("type") != session_type:
            continue
        payload["path"] = str(file)
        sessions.append(payload)
    return sessions


def load_pending_shell() -> Optional[Dict[str, Any]]:
    sessions = list_pending("shell")
    if not sessions:
        return None
    # Return the most recently updated session
    sessions.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return sessions[0]


def archive_session(session_type: str, session_id: str) -> None:
    complete_session(session_type, session_id)


def resume_summary() -> str:
    sessions = list_pending()
    if not sessions:
        return "No pending sessions."
    lines = ["Pending sessions:"]
    for item in sessions:
        lines.append(
            f" - {item.get('type')}:{item.get('session_id')} (updated {item.get('updated_at')})"
        )
    return "\n".join(lines)
