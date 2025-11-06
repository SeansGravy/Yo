from __future__ import annotations

import asyncio
import logging

from yo.brain import YoBrain


class DummyBrain:
    def __init__(self) -> None:
        self.model_name = "dummy"
        self.active_namespace = "default"
        self._logger = logging.getLogger("dummy-brain")

    def chat(
        self,
        *,
        message: str,
        namespace: str | None = None,
        history: list[dict[str, str]] | None = None,
        web: bool = False,
        stream: bool = False,
    ) -> dict[str, str]:
        assert stream is False
        return {"response": f"echo:{message}"}


def test_chat_async_returns_text() -> None:
    brain = DummyBrain()

    async def _invoke() -> dict[str, str]:
        return await YoBrain.chat_async(  # type: ignore[misc]
            brain,
            message="ping",
            namespace="default",
            history=None,
            web=False,
            timeout=2.0,
        )

    result = asyncio.run(_invoke())
    assert "text" in result
    assert result["text"] == "echo:ping"
