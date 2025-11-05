"""WebSocket broadcaster utilities for Yo."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Iterable, List, Sequence, Set

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


def _log_ws_error(message: str) -> None:
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
            except Exception:  # pragma: no cover - network failure
                _log_ws_error(f"broadcast to {getattr(websocket, 'client', 'unknown')} failed")
                stale.append(websocket)
        for ws in stale:
            await self.disconnect(ws)

    async def _build_payload(self) -> dict:
        result = self._builder()
        if asyncio.iscoroutine(result):
            result = await result
        return result or {}
