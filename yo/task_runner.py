"""Codex task lifecycle runner."""

from __future__ import annotations

from pathlib import Path
import shutil
import datetime
import sys
import importlib


def run_tasks() -> None:
    tasks_root = Path("tasks")
    active = tasks_root / "active"
    completed = tasks_root / "completed"
    failed = tasks_root / "failed"

    for directory in (active, completed, failed):
        directory.mkdir(parents=True, exist_ok=True)

    for card in active.glob("*.md"):
        name = card.name
        print(f"[Codex] Running {name}")
        start = datetime.datetime.utcnow().isoformat()
        version = _get_version()
        destination = completed / name

        try:
            content = card.read_text(encoding="utf-8")
            log = "\n---\n## 🧾 Codex Execution Log\n✅ Completed {}\n".format(start)
            card.write_text(content + log, encoding="utf-8")
            shutil.move(card, destination)
            print(f"[Codex] {name} → completed")
            _print_success_echo(version, destination)
        except Exception as exc:  # pragma: no cover - defensive path
            shutil.move(card, failed / name)
            print(f"[Codex] {name} → failed ({exc})")


def _get_version() -> str:
    try:
        module = importlib.import_module("yo")
        return getattr(module, "__version__", "unknown")
    except Exception:  # pragma: no cover
        return "unknown"


def _print_success_echo(version: str, archived_path: Path) -> None:
    print(f"✅ Codex build complete — Yo current version: {version}")
    print(f"🗂️ Task archived → {archived_path}")
    print("📄 Results appended.")
    print("───────────────────────────────")
    print("Manual Publish Commands:")
    commands = [
        "git add -A",
        "git commit -m \"<commit message>\"",
        f"git tag -a {version} -m \"<tag message>\"",
        "git push origin main --tags",
    ]
    for cmd in commands:
        print(cmd)
    print("───────────────────────────────")
    print("Please run these commands to publish to the repository.")


if __name__ == "__main__":
    run_tasks()
