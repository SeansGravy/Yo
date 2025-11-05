from __future__ import annotations

from yo.chat import ChatSessionStore


class StubBrain:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        history = kwargs.get("history") or []
        return {
            "response": f"Reply {len(history) + 1}",
            "context": "context",
            "citations": ["reference.md"],
        }


def test_chat_session_store_persists_history() -> None:
    store = ChatSessionStore()
    brain = StubBrain()

    session_id, reply, history, metadata = store.send(
        brain=brain,
        namespace="default",
        message="Hello",
    )
    assert reply == "Reply 1"
    assert history == [{"user": "Hello", "assistant": "Reply 1"}]
    assert metadata["citations"] == ["reference.md"]

    session_id_again, reply2, history2, _ = store.send(
        brain=brain,
        namespace="default",
        message="How are you?",
        session_id=session_id,
    )
    assert session_id_again == session_id
    assert len(history2) == 2
    assert history2[-1]["assistant"] == "Reply 2"
    assert brain.calls[-1]["history"][0]["user"] == "Hello"
