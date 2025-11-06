from __future__ import annotations

import logging
from typing import Any, List, Tuple

import pytest

import yo.brain as brain_mod


def test_chat_reply_propagates_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run_ollama_chat(model: str, prompt: str, stream: bool = False, **_: Any) -> str:
        return "hello world"

    monkeypatch.setattr(brain_mod, "run_ollama_chat", _fake_run_ollama_chat)

    brain = brain_mod.YoBrain.__new__(brain_mod.YoBrain)  # type: ignore[misc]
    brain.model_name = "dummy"  # type: ignore[attr-defined]
    brain._logger = logging.getLogger("yo-brain-test")  # type: ignore[attr-defined]

    def _fake_prepare(
        message: str,
        namespace: str,
        history: List[dict[str, str]] | None,
        web: bool,
    ) -> Tuple[List[dict[str, str]], str, List[str]]:
        return [{"role": "user", "content": message}], "", []

    brain._prepare_chat = _fake_prepare  # type: ignore[attr-defined]

    result = brain.chat(message="say hello", namespace="default", history=None, web=False, stream=False)
    assert isinstance(result, dict)
    reply = result.get("reply")
    assert isinstance(reply, dict)
    assert reply.get("text") == "hello world"
    assert result.get("response") == "hello world"
