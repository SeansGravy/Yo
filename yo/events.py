"""Simple asynchronous event bus for Yo."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set

MAX_EVENT_HISTORY = 200
EVENT_LOG_PATH = Path("data/logs/events.jsonl")
EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


class EventBus:
    """Lightweight pub/sub bus for async event delivery."""

    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._history: deque[dict[str, Any]] = deque(maxlen=MAX_EVENT_HISTORY)

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
            for event in self._history:
                await queue.put(event)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = {"type": event_type, **payload}
        event.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
        async with self._lock:
            self._history.append(event)
            subscribers = tuple(self._subscribers)
        try:
            with EVENT_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        except OSError:
            pass
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                continue


_GLOBAL_BUS = EventBus()


def get_event_bus() -> EventBus:
    return _GLOBAL_BUS


def publish_event(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    payload = payload or {}
    bus = get_event_bus()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(bus.publish(event_type, payload))
        return
    loop.create_task(bus.publish(event_type, payload))
