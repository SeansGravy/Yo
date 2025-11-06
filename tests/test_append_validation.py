from __future__ import annotations

from pathlib import Path

from yo.hooks.codex_finalize import finalize_task


def test_append_validation(tmp_path: Path) -> None:
    card = tmp_path / "card.md"
    card.write_text("# test", encoding="utf-8")
    context = {"operator": "Sean Gray", "cwd": str(tmp_path)}

    result = finalize_task(card, context)
    data = card.read_text(encoding="utf-8")

    assert "🧠 Version:" in data
    assert "📘 Notes:" in data
    assert result["validation_status"] == "valid"
