"""WatchFiles-based reload supervisor with debounce and ignore support."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence

from yo.logging_utils import get_logger

try:  # pragma: no cover - optional dependency
    from watchfiles import awatch
except ModuleNotFoundError:  # pragma: no cover - handled at runtime via guard
    awatch = None  # type: ignore[assignment]


DEFAULT_DEBOUNCE = 1.5
DEFAULT_IGNORE_GLOBS: tuple[str, ...] = ("tests/test_memory.py",)


class ReloadableTarget(Protocol):
    async def serve(self) -> None: ...

    def request_shutdown(self) -> None: ...


class WatchFilesReloader:
    """Coordinate a reloadable target driven by WatchFiles file change events."""

    def __init__(
        self,
        target_factory: Callable[[], ReloadableTarget],
        *,
        reload_paths: Sequence[Path | str],
        debounce: float = DEFAULT_DEBOUNCE,
        ignore_globs: Sequence[str] = DEFAULT_IGNORE_GLOBS,
    ) -> None:
        if awatch is None:  # pragma: no cover - defers dependency error to runtime
            raise RuntimeError(
                "watchfiles is not installed. Install it to enable reload support."
            )

        paths: list[Path] = []
        for entry in reload_paths:
            candidate = Path(entry)
            if not candidate.exists():
                candidate.mkdir(parents=True, exist_ok=True)
            resolved = candidate.resolve()
            paths.append(resolved)
        if not paths:
            paths = [Path.cwd()]

        self._target_factory = target_factory
        self._reload_paths = paths
        self._debounce = debounce
        self._ignore_globs = tuple(ignore_globs)
        self._logger = get_logger(__name__)

        self._target: ReloadableTarget | None = None
        self._server_task: asyncio.Task[None] | None = None

    async def _start_server(self) -> None:
        self._target = self._target_factory()
        self._server_task = asyncio.create_task(self._target.serve())
        self._logger.info(
            "🚀 Started server task (watching: %s)",
            ", ".join(path.as_posix() for path in self._reload_paths),
        )

    async def _stop_server(self) -> None:
        if self._target is None:
            return
        self._target.request_shutdown()
        if self._server_task:
            await self._server_task
        self._logger.info("✅ Server shutdown complete.")
        self._target = None
        self._server_task = None

    def _should_ignore(self, path: Path) -> bool:
        return any(path.match(pattern) for pattern in self._ignore_globs)

    async def _next_change(self) -> set[tuple[int, str]]:
        assert awatch is not None  # help type-checker

        async for changes in awatch(
            *[str(path) for path in self._reload_paths],
            debounce=self._debounce,
        ):
            filtered = {
                (change, file_path)
                for change, file_path in changes
                if not self._should_ignore(Path(file_path))
            }
            if filtered:
                return filtered
        return set()

    async def run(self) -> None:
        """Run the supervisor until the underlying server stops."""

        await self._start_server()

        try:
            while True:
                if self._server_task is None:
                    break

                watch_task = asyncio.create_task(self._next_change())
                done, _ = await asyncio.wait(
                    {self._server_task, watch_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if self._server_task in done:
                    watch_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await watch_task
                    break

                changes = watch_task.result()
                self._logger.info(
                    "♻️  Reload triggered by: %s",
                    ", ".join(Path(path).name for _, path in changes),
                )
                await self._stop_server()
                await self._start_server()
        finally:
            if self._server_task is not None:
                self._target.request_shutdown()
                with suppress(asyncio.CancelledError):
                    await self._server_task
                self._server_task = None
            self._logger.info("🛑 Reload supervisor exiting.")


class UvicornTarget:
    """Reloadable target backed by a uvicorn configuration factory."""

    def __init__(self, config_factory: Callable[[], Any]) -> None:
        self._config_factory = config_factory
        self._server: Any | None = None

    async def serve(self) -> None:
        import uvicorn

        config = self._config_factory()
        self._server = uvicorn.Server(config)
        await self._server.serve()

    def request_shutdown(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


def create_uvicorn_config_factory(app: str, **kwargs: Any) -> Callable[[], Any]:
    """Return a factory that yields a fresh uvicorn.Config on each invocation."""

    def _factory() -> Any:
        import uvicorn

        params = dict(kwargs)
        params.setdefault("reload", False)
        params.setdefault("log_level", "info")
        return uvicorn.Config(app, **params)

    return _factory


async def serve_uvicorn_with_watchfiles(
    config_factory: Callable[[], Any],
    *,
    reload_dirs: Sequence[Path | str] | None = None,
    debounce: float = DEFAULT_DEBOUNCE,
    ignore_globs: Sequence[str] = DEFAULT_IGNORE_GLOBS,
) -> None:
    """Run uvicorn with a WatchFiles-based reload supervisor."""

    paths: list[Path] = []
    if reload_dirs:
        paths.extend(Path(entry) for entry in reload_dirs)
    else:
        paths.extend([Path("yo"), Path("docs")])

    target_factory = lambda: UvicornTarget(config_factory)
    supervisor = WatchFilesReloader(
        target_factory,
        reload_paths=paths,
        debounce=debounce,
        ignore_globs=ignore_globs,
    )
    await supervisor.run()


__all__ = [
    "DEFAULT_DEBOUNCE",
    "DEFAULT_IGNORE_GLOBS",
    "WatchFilesReloader",
    "UvicornTarget",
    "create_uvicorn_config_factory",
    "serve_uvicorn_with_watchfiles",
]
