from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yo.reloader as reloader_module
from yo.reloader import DEFAULT_DEBOUNCE, WatchFilesReloader, serve_uvicorn_with_watchfiles


def test_next_change_skips_ignored_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    events = [
        {(1, "tests/test_memory.py")},
        {(1, str(tmp_path / "yo" / "brain.py"))},
    ]
    captured: dict[str, object] = {}

    async def fake_awatch(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        for event in events:
            yield event

    monkeypatch.setattr(reloader_module, "awatch", fake_awatch)

    target = SimpleNamespace(serve=lambda: asyncio.sleep(0), request_shutdown=lambda: None)
    reloader = WatchFilesReloader(lambda: target, reload_paths=[tmp_path / "yo"])

    result = asyncio.run(reloader._next_change())

    assert captured["args"] == (str(tmp_path / "yo"),)
    assert (1, str(tmp_path / "yo" / "brain.py")) in result
    assert captured["kwargs"]["debounce"] == DEFAULT_DEBOUNCE


def test_serve_uvicorn_with_watchfiles_configures_supervisor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}

    class DummySupervisor:
        def __init__(self, target_factory, *, reload_paths, debounce, ignore_globs):
            recorded["reload_paths"] = tuple(Path(p) for p in reload_paths)
            recorded["debounce"] = debounce
            recorded["ignore_globs"] = tuple(ignore_globs)
            self._target_factory = target_factory

        async def run(self):
            recorded["run_called"] = True

    monkeypatch.setattr(reloader_module, "WatchFilesReloader", DummySupervisor)

    def fake_config_factory():
        recorded["config_requested"] = True
        return {"app": "test"}

    asyncio.run(
        serve_uvicorn_with_watchfiles(
            fake_config_factory,
            reload_dirs=[tmp_path / "yo"],
            debounce=2.0,
            ignore_globs=("*.tmp",),
        )
    )

    assert recorded["run_called"] is True
    assert recorded["debounce"] == 2.0
    assert recorded["ignore_globs"] == ("*.tmp",)
