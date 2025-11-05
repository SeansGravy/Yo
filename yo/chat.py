"""In-memory chat session management for Yo."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from yo.events import publish_event

CHAT_LOG_DIR = Path("data/logs/chat_sessions")


@dataclass
class ChatTurn:
    user: str
    assistant: str


@dataclass
class ChatSession:
    session_id: str
    namespace: str
    history: List[ChatTurn] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def as_history(self) -> List[Dict[str, str]]:
        return [{"user": turn.user, "assistant": turn.assistant} for turn in self.history]


class ChatSessionStore:
    """Simple in-memory chat session store keyed by session id."""

    def __init__(self) -> None:
        self._sessions: Dict[str, ChatSession] = {}
        self._lock = threading.RLock()

    def _new_session(self, namespace: str, session_id: str | None = None) -> ChatSession:
        session_id = session_id or uuid.uuid4().hex
        session = ChatSession(session_id=session_id, namespace=namespace)
        self._sessions[session_id] = session
        return session

    def session(self, session_id: str | None) -> ChatSession | None:
        if not session_id:
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()

    def send(
        self,
        *,
        brain: Any,
        namespace: str,
        message: str,
        session_id: str | None = None,
        web: bool = False,
    ) -> Tuple[str, str, List[Dict[str, str]], Dict[str, Any]]:
        """Generate a response for ``message`` and update the stored history."""

        if not message:
            raise ValueError("Message cannot be empty.")

        with self._lock:
            session = self._sessions.get(session_id) if session_id else None
            if session is None or session.namespace != namespace:
                session = self._new_session(namespace, session_id)
            history_payload = session.as_history()

        reply_data = brain.chat(
            message=message,
            namespace=namespace,
            history=history_payload,
            web=web,
        )
        reply_text = reply_data.get("response", "")

        with self._lock:
            session = self._sessions.get(session.session_id, session)  # type: ignore[arg-type]
            session.history.append(ChatTurn(user=message, assistant=reply_text))
            session.updated_at = datetime.utcnow().isoformat() + "Z"
            history_snapshot = session.as_history()
            self._write_transcript(session)

        publish_event(
            "chat_message",
            {
                "session_id": session.session_id,
                "namespace": namespace,
                "message": message,
                "reply": reply_text,
            },
        )

        metadata = {
            "context": reply_data.get("context"),
            "citations": reply_data.get("citations") or [],
        }
        return session.session_id, reply_text, history_snapshot, metadata

    def stream(
        self,
        *,
        brain: Any,
        namespace: str,
        message: str,
        session_id: str | None = None,
        web: bool = False,
    ) -> Tuple[str, str, List[Dict[str, str]], Dict[str, Any]]:
        if not message:
            raise ValueError("Message cannot be empty.")

        with self._lock:
            session = self._sessions.get(session_id) if session_id else None
            if session is None or session.namespace != namespace:
                session = self._new_session(namespace, session_id)
            history_payload = session.as_history()

        publish_event(
            "chat_started",
            {
                "session_id": session.session_id,
                "namespace": namespace,
                "message": message,
            },
        )

        for chunk in brain.chat_stream(
            message=message,
            namespace=namespace,
            history=history_payload,
            web=web,
        ):
            if chunk.get("done"):
                reply_text = chunk.get("response", "")
                citations = chunk.get("citations") or []
                with self._lock:
                    session = self._sessions.get(session.session_id, session)  # type: ignore[arg-type]
                    session.history.append(ChatTurn(user=message, assistant=reply_text))
                    session.updated_at = datetime.utcnow().isoformat() + "Z"
                    history_snapshot = session.as_history()
                    self._write_transcript(session)

                metadata = {
                    "context": chunk.get("context"),
                    "citations": citations,
                }
                publish_event(
                    "chat_complete",
                    {
                        "session_id": session.session_id,
                        "namespace": namespace,
                        "reply": reply_text,
                        "history": history_snapshot,
                    },
                )
                return session.session_id, reply_text, history_snapshot, metadata

            token = chunk.get("token", "")
            if token:
                publish_event(
                    "chat_token",
                    {
                        "session_id": session.session_id,
                        "namespace": namespace,
                        "token": token,
                    },
                )

        raise RuntimeError("Streaming chat ended unexpectedly without completion.")

    def _write_transcript(self, session: ChatSession) -> None:
        transcript_path = CHAT_LOG_DIR / f"chat_{session.session_id}.json"
        transcript = {
            "session_id": session.session_id,
            "namespace": session.namespace,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "history": session.as_history(),
        }
        try:
            transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
        except OSError:
            pass
