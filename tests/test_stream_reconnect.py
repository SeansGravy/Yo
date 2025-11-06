from __future__ import annotations

import asyncio
import logging

import pytest

from yo import brain as brain_mod
from yo.backends import OllamaStreamTimeout


@pytest.mark.asyncio
async def test_chat_stream_attempts_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    brain = brain_mod.YoBrain.__new__(brain_mod.YoBrain)  # type: ignore[misc]
    brain._logger = logging.getLogger("yo-brain-test")  # type: ignore[attr-defined]
    brain.model_name = "dummy"  # type: ignore[attr-defined]
    brain.active_namespace = "default"  # type: ignore[attr-defined]
    brain._prepare_chat = lambda message, namespace, history, web: ([{"role": "user", "content": message}], "", [])  # type: ignore[attr-defined]

    call_counter = {"count": 0}

    async def fake_stream(*args, **kwargs):
        call_counter["count"] += 1
        if call_counter["count"] < 3:
            raise OllamaStreamTimeout("silence")
        yield "hello "
        yield "world"

    async def fake_sleep(_: float) -> None:
        return None

    metrics_calls: list[tuple[str, dict]] = []

    def fake_record_metric(metric_type: str, **fields):
        metrics_calls.append((metric_type, fields))
        return {"type": metric_type, **fields}

    monkeypatch.setattr(brain_mod, "stream_ollama_chat", fake_stream)
    monkeypatch.setattr(brain_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(brain_mod, "record_metric", fake_record_metric)

    chunks = []
    async for chunk in brain.chat_stream_async(
        message="hi",
        namespace="default",
        history=None,
        web=False,
        timeout=10.0,
    ):
        chunks.append(chunk)

    assert call_counter["count"] == 3
    assert chunks[-1]["done"] is True
    assert chunks[-1]["response"].startswith("hello world")

    metric_names = [name for name, _ in metrics_calls]
    assert "stream_timeout" in metric_names
    assert "stream_reconnect_attempts" in metric_names
    assert "stream_drops" not in metric_names
