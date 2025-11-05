"""WebSocket broadcaster utilities for Yo."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Sequence, Set

from fastapi import WebSocket

from yo.events import publish_event
from yo.logging_utils import get_logger

try:  # pragma: no cover - watchfiles optional
    from watchfiles import awatch
except ImportError:  # pragma: no cover
    awatch = None  # type: ignore[assignment]


PayloadBuilder = Callable[[], dict | Awaitable[dict]]

LOGGER = get_logger(__name__)
WS_ERROR_LOG = Path("data/logs/ws_errors.log")
CHAT_TIMING_LOG = Path("data/logs/chat_timing.log")
CHAT_TIMING_JSONL = Path("data/logs/chat_timing.jsonl")


def _write_chat_timing_entry(entry: Dict[str, Any]) -> None:
    try:
        CHAT_TIMING_LOG.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(entry)
        with CHAT_TIMING_LOG.open("a", encoding="utf-8") as log_file:
            log_file.write(payload + "\n")
        with CHAT_TIMING_JSONL.open("a", encoding="utf-8") as jsonl_file:
            jsonl_file.write(payload + "\n")
    except OSError:
        LOGGER.warning("Unable to persist chat timing entry.")


def _extract_text_len(payload: Dict[str, Any]) -> int:
    reply = payload.get("reply")
    if isinstance(reply, dict):
        text = reply.get("text")
        if isinstance(text, str):
            return len(text.strip())
    elif isinstance(reply, str):
        return len(reply.strip())
    token = payload.get("token")
    if isinstance(token, str):
        return len(token)
    return 0


def _log_chat_emit(session_id: str, namespace: str | None, event_type: str, success: bool, *, text_len: int, error: str | None = None, latency_ms: float | None = None) -> None:
    entry: Dict[str, Any] = {
        "event": "chat_emit_success" if success else "chat_emit_error",
        "session_id": session_id,
        "namespace": namespace,
        "event_type": event_type,
        "success": success,
        "text_len": text_len,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    if latency_ms is not None:
        entry["latency_ms"] = latency_ms
    if error:
        entry["error"] = error
    _write_chat_timing_entry(entry)


def log_ws_error(message: str) -> None:
    try:
        WS_ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().isoformat() + "Z"
        with WS_ERROR_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except OSError:
        pass
    LOGGER.warning("WebSocket broadcast failure: %s", message)


class UpdateBroadcaster:
    """Broadcast filesystem-driven updates to connected WebSocket clients."""

    def __init__(self, watch_targets: Iterable[Path], builder: PayloadBuilder, *, event_type: str | None = None) -> None:
        self.watch_targets = [Path(target) for target in watch_targets]
        self._builder = builder
        self._event_type = event_type
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._watch_task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self) -> None:
        if awatch is None or self._watch_task is not None:
            return
        self._stop_event = asyncio.Event()
        self._watch_task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        if self._watch_task:
            if self._stop_event:
                self._stop_event.set()
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:  # pragma: no cover - normal shutdown
                pass
            self._watch_task = None

    async def _watch_loop(self) -> None:
        if awatch is None:
            return

        targets: List[str] = []
        for target in self.watch_targets:
            if target.is_dir() or target.exists():
                targets.append(str(target))
            else:
                # Watch the parent directory so newly created files still trigger updates.
                targets.append(str(target.parent))

        if not targets:
            return

        try:
            async for _ in awatch(
                *targets,
                stop_event=self._stop_event,
                debounce=1.0,
            ):
                await self.trigger()
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            return

    async def connect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def trigger(self) -> None:
        payload = await self._build_payload()
        await self.broadcast(payload)

    async def broadcast(self, payload: dict) -> None:
        if not payload:
            return
        message = json.dumps(payload)
        if self._event_type:
            publish_event(self._event_type, payload)
        async with self._lock:
            connections: Sequence[WebSocket] = tuple(self._connections)

        stale: List[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_text(message)
                await asyncio.sleep(0)
            except Exception:  # pragma: no cover - network failure
                log_ws_error(f"broadcast to {getattr(websocket, 'client', 'unknown')} failed")
                stale.append(websocket)
        for ws in stale:
            await self.disconnect(ws)

    async def _build_payload(self) -> dict:
        result = self._builder()
        if asyncio.iscoroutine(result):
            result = await result
        return result or {}


class ConnectionManager:
    """Track active chat WebSocket connections by session id."""

    def __init__(self) -> None:
        self._active: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            connections = self._active.setdefault(session_id, set())
            connections.add(websocket)

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._active.get(session_id)
            if not connections:
                return
            connections.discard(websocket)
            if not connections:
                self._active.pop(session_id, None)

    async def send(self, session_id: str, payload: Dict[str, Any]) -> None:
        event_type = payload.get("type") or payload.get("event") or "unknown"
        namespace = payload.get("namespace")
        latency_ms = payload.get("first_token_latency_ms") or payload.get("latency_ms")
        async with self._lock:
            targets = tuple(self._active.get(session_id, ()))

        if not targets:
            _log_chat_emit(
                session_id,
                namespace,
                event_type,
                success=False,
                text_len=_extract_text_len(payload),
                error="no_active_connection",
                latency_ms=latency_ms,
            )
            return

        successes = 0
        failures: List[str] = []
        stale: List[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(payload)
                successes += 1
            except Exception as exc:  # pragma: no cover - transport failure
                log_ws_error(f"chat emit failed session={session_id}: {exc}")
                failures.append(str(exc))
                stale.append(websocket)

        for websocket in stale:
            await self.disconnect(session_id, websocket)

        success = successes > 0
        error_message = None
        if failures and not success:
            error_message = failures[0]
        elif failures:
            error_message = "partial_failure"

        _log_chat_emit(
            session_id,
            namespace,
            event_type,
            success=success,
            text_len=_extract_text_len(payload),
            error=error_message,
            latency_ms=latency_ms,
        )
