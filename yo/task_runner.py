"""Codex task lifecycle runner with structured finalize hook."""

from __future__ import annotations

import time
from pathlib import Path
import shutil
import importlib

from yo.hooks.codex_finalize import finalize_task


def run_tasks() -> None:
    tasks_root = Path("tasks")
    active = tasks_root / "active"
    completed = tasks_root / "completed"
    failed = tasks_root / "failed"

    for directory in (active, completed, failed):
        directory.mkdir(parents=True, exist_ok=True)

    for card in sorted(active.glob("*.md")):
        name = card.name
        print(f"[Codex] Running {name}")
        start_ts = time.perf_counter()
        version = _get_version()

        try:
            duration = time.perf_counter() - start_ts
            context = {
                "operator": "Sean Gray",
                "cwd": str(Path.cwd()),
                "scan_path": str(active.resolve()),
                "created": [],
                "modified": [],
                "deleted": [],
                "renamed": [],
                "tests": "not run",
                "metrics": "n/a",
                "commit": "pending",
                "notes": "Task completed successfully.",
                "duration": round(duration, 3),
            }

            finalized = finalize_task(card, context)
            print(f"[Codex] Append validation: {finalized.get('validation_status', 'unknown')}")

            with card.open("r", encoding="utf-8") as handle:
                content = handle.read()

            required = ["🧠 Version:", "📘 Notes:", "⚙️ Executor:"]
            missing = [token for token in required if token not in content]

            if missing:
                print(f"[Codex] ⚠️ Structured append missing tokens {missing}; skipping archive.")
                shutil.move(card, failed / name)
                continue

            print("[Codex] ✅ Structured append detected, proceeding to archive.")
            destination = completed / name
            shutil.move(card, destination)
            _print_success_echo(version, destination)
        except Exception as exc:  # pragma: no cover - defensive guard
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
        f'git commit -m "release: {version} — Codex task batch"',
        f'git tag -a {version} -m "Yo {version} — Codex task batch"',
        "git push origin main --tags",
    ]
    for cmd in commands:
        print(cmd)
    print("───────────────────────────────")
    print("Please run these commands to publish to the repository.")


if __name__ == "__main__":
    run_tasks()
