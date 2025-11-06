"""Command line entry point for Yo."""

from __future__ import annotations

import argparse
import asyncio
import html
import io
import json
import os
import re
import socket
import subprocess
import sys
import shutil
import time
import zipfile
from collections import deque
from datetime import datetime, timedelta, timezone
from statistics import mean
from importlib import metadata as importlib_metadata
from importlib import util as import_util
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional, Sequence

Status = Literal["ok", "warn", "fail"]

from packaging.version import InvalidVersion, Version

from yo.backends import detect_backends
from yo.brain import IngestionError, MissingDependencyError, YoBrain
from yo.config import ENV_FILE, get_config, reset_config, serialize_config, update_config_value
from yo.deps import (
    deps_check_command,
    deps_freeze_command,
    deps_repair_command,
    deps_diff_command,
    deps_sync_command,
)
from yo.verify import run_pytest_with_metrics, write_test_summary
from yo.telemetry import (
    archive_telemetry,
    build_telemetry_summary,
    compute_health_score,
    compute_trend,
    list_archives,
    load_dependency_history,
    load_telemetry_summary,
    load_test_history,
    load_test_summary,
    summarize_failures,
)
from yo.release import (
    build_release_bundle,
    load_integrity_manifest,
    load_release_manifest,
    list_release_manifests,
    verify_integrity_manifest,
)
from yo.signing import verify_signature
from yo.system_tools import (
    load_lifecycle_history,
    list_snapshots,
    system_clean,
    system_snapshot,
    system_restore,
)
from yo import recovery
from yo.chat import CHAT_DAILY_DIR
from yo.events import EVENT_LOG_DIR, publish_event
import httpx
import websockets
from yo.metrics import summarize_since, parse_since_window, record_metric
from yo.analytics import analytics_enabled, load_analytics, record_cli_command, summarize_usage
from yo.optimizer import generate_recommendations, apply_recommendations

try:  # pragma: no cover - optional dependency
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
except ImportError:  # pragma: no cover - rich is optional
    Console = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]

console: Optional[Console] = Console() if Console is not None else None

SESSION_LOG_ROOT = recovery.SESSION_ROOT
SHELL_LOG_DIR = SESSION_LOG_ROOT / "shell"
SHELL_LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_KINDS = {
    "events": EVENT_LOG_DIR,
    "chat": CHAT_DAILY_DIR,
    "shell": SHELL_LOG_DIR,
    "ws": Path("data/logs/ws_errors.log"),
}
CHAT_PAGE_WARN_THRESHOLD_MS = 1000.0
CHAT_TIMING_LOG = Path("data/logs/chat_timing.log")
CHAT_TIMING_JSONL = Path("data/logs/chat_timing.jsonl")
WS_ERROR_LOG = Path("data/logs/ws_errors.log")


def _rich_print(*args: object, style: str | None = None) -> None:
    if console is not None:
        console.print(*args, style=style)
    else:
        if style:
            print(" ".join(str(arg) for arg in args))
        else:
            print(*args)


def _yo_version() -> str:
    try:
        version = importlib_metadata.version("yo")
    except importlib_metadata.PackageNotFoundError:
        version = os.environ.get("YO_VERSION", "0.3.8")
    version = str(version)
    return version if version.startswith("v") else f"v{version}"


def _display_verify_banner(summary: Dict[str, Any]) -> None:
    telemetry_summary = load_telemetry_summary() or build_telemetry_summary()
    health_raw = telemetry_summary.get("health_score")
    if isinstance(health_raw, (int, float)):
        health_display = f"{health_raw:.0f}"
    else:
        health_display = "n/a"

    pass_rate = summary.get("pass_rate")
    if isinstance(pass_rate, (int, float)):
        pass_rate_pct = pass_rate * 100 if pass_rate <= 1 else pass_rate
        pass_rate_display = f"{pass_rate_pct:.0f}%"
    else:
        total = summary.get("tests_total") or 0
        passed = summary.get("tests_passed") or 0
        pass_rate_display = f"{passed}/{total}"

    namespace = summary.get("namespace") or get_config().namespace
    header = f"🧠 Yo {_yo_version()} | Namespace: {namespace} | Health: {health_display} | Pass Rate: {pass_rate_display}"

    if console and Panel:
        console.print(Panel.fit(header, border_style="green"))
    else:
        print(header)


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_log_path(kind: str) -> Path | None:
    path_hint = LOG_KINDS.get(kind)
    if path_hint is None:
        return None
    path_hint = Path(path_hint)
    if path_hint.suffix:
        return path_hint if path_hint.exists() else None
    candidates = []
    for path in path_hint.glob("*.jsonl"):
        if not path.is_file():
            continue
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def _read_log_tail(log_path: Path, lines: int) -> list[str]:
    if lines <= 0:
        lines = 20
    buffer: deque[str] = deque(maxlen=lines)
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                buffer.append(raw.rstrip("\n"))
    except OSError:
        return []
    return list(buffer)


def _tail_file(path: Path, max_lines: int = 50) -> str:
    try:
        with path.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return ""
    return "".join(lines[-max_lines:])


def _format_log_entry(kind: str, raw_line: str) -> str:
    try:
        record = json.loads(raw_line)
    except json.JSONDecodeError:
        return raw_line

    timestamp = record.get("timestamp", "")

    if kind == "chat":
        event = record.get("event")
        session = record.get("session_id", "unknown")
        namespace = record.get("namespace", "default")
        if event == "token":
            token = record.get("token", "")
            return f"{timestamp} [{namespace}:{session}] token: {token}"
        if event == "message":
            user = record.get("user", "")
            reply = record.get("assistant", "")
            return f"{timestamp} [{namespace}:{session}] user: {user!r} → assistant: {reply!r}"
        if event == "complete":
            reply = record.get("assistant", "")
            return f"{timestamp} [{namespace}:{session}] complete: {reply!r}"
        return f"{timestamp} [{namespace}:{session}] {event}"

    if kind == "events":
        event_type = record.get("type", "event")
        payload = {
            key: value
            for key, value in record.items()
            if key not in {"type", "timestamp"} and value not in ("", None)
        }
        detail = ", ".join(f"{key}={value}" for key, value in payload.items())
        detail_text = f": {detail}" if detail else ""
        return f"{timestamp} {event_type}{detail_text}"

    if kind == "shell":
        event = record.get("event", "event")
        session = record.get("session_id", "unknown")
        namespace = record.get("namespace", "default")
        if event == "command":
            command = record.get("command", "")
            return f"{timestamp} [{namespace}:{session}] command -> {command}"
        if event == "start":
            cwd = record.get("cwd", "")
            return f"{timestamp} [{namespace}:{session}] shell started (cwd={cwd})"
        if event == "end":
            return f"{timestamp} [{namespace}:{session}] shell ended"
        return f"{timestamp} [{namespace}:{session}] {event}"

    return raw_line


Handler = Callable[[argparse.Namespace, YoBrain | None], None]

MAIN_PARSER: Optional[argparse.ArgumentParser] = None
COMMAND_REGISTRY: Dict[str, Dict[str, Any]] = {}
COMMAND_CATEGORIES: Dict[str, str] = {
    "add": "Ingestion",
    "ask": "Retrieval",
    "chat": "Retrieval",
    "shell": "Utilities",
    "summarize": "Retrieval",
    "namespace": "Namespace",
    "ns": "Namespace",
    "config": "Configuration",
    "deps": "Dependencies",
    "telemetry": "Telemetry",
    "explain": "Telemetry",
    "dashboard": "Insights",
    "web": "Utilities",
    "metrics": "Insights",
    "analytics": "Insights",
    "optimize": "Insights",
    "cache": "Utilities",
    "compact": "Maintenance",
    "package": "Release",
    "release": "Release",
    "verify": "Validation",
    "doctor": "Validation",
    "health": "Insights",
    "logs": "Insights",
    "system": "Maintenance",
    "report": "Insights",
    "help": "Utilities",
}
ALIAS_EXPANSIONS: Dict[str, list[str]] = {
    "t": ["telemetry", "analyze"],
    "h": ["health", "report"],
}

SINCE_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[hdw])$")
DEFAULT_DRIFT_WINDOW = "7d"
NAMESPACE_DOCUMENT_ALERT = 1000
NAMESPACE_CHUNK_ALERT = 5000
NAMESPACE_GROWTH_ALERT = 75.0


def _register_command(
    name: str,
    parser: argparse.ArgumentParser,
    *,
    help_text: str,
    category: Optional[str] = None,
    aliases: Optional[Sequence[str]] = None,
    parent: Optional[str] = None,
    primary: bool = True,
) -> None:
    category = category or COMMAND_CATEGORIES.get(name, "General")
    entry = {
        "name": name,
        "category": category,
        "help": help_text,
        "parser": parser,
        "aliases": list(aliases or []),
        "parent": parent,
        "primary": primary,
    }
    COMMAND_REGISTRY[name] = entry
    for alias in aliases or []:
        COMMAND_REGISTRY[alias] = {
            **entry,
            "name": alias,
            "primary": False,
            "alias_of": name,
        }


def _expand_aliases(argv: Sequence[str]) -> list[str]:
    if len(argv) < 2:
        return list(argv)
    alias = argv[1]
    expansion = ALIAS_EXPANSIONS.get(alias)
    if not expansion:
        return list(argv)
    return [argv[0], *expansion, *argv[2:]]


def _verify_signature_artifacts() -> dict[str, Any]:
    checksum_path = Path("data/logs/checksums/artifact_hashes.txt")
    signature_path = Path("data/logs/checksums/artifact_hashes.sig")
    key_path = Path("data/logs/checksums/artifact_signing_public.asc")
    result = verify_signature(signature_path, checksum_path, key_path=key_path)
    result["checksum"] = str(checksum_path)
    result["signature"] = str(signature_path)
    return result


def _format_timestamp(raw: Optional[str]) -> str:
    if not raw:
        return "never"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    return dt.strftime("%Y-%m-%d %H:%M")


def _parse_since(value: Optional[str]) -> timedelta:
    token = (value or DEFAULT_DRIFT_WINDOW).strip().lower()
    match = SINCE_PATTERN.match(token)
    if not match:
        raise ValueError("Duration must use forms like '24h', '7d', or '2w'.")
    amount = int(match.group("value"))
    unit = match.group("unit")
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "w":
        return timedelta(weeks=amount)
    raise ValueError("Unsupported duration unit.")

CONFIG_MUTABLE_KEYS: tuple[str, ...] = (
    "namespace",
    "model",
    "embed_model",
    "db_uri",
)


def _active_namespace_default() -> str:
    try:
        return get_config().namespace
    except Exception:
        return "default"


def _resolve_namespace_arg(args: argparse.Namespace) -> str:
    name = getattr(args, "name", None) or getattr(args, "ns", None)
    if not name:
        raise ValueError("Namespace name is required. Provide a name or pass `--ns default`.")
    return str(name)


def run_test(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    """Execute the regression test script if available."""

    script = Path.cwd() / "yo_full_test.sh"
    if not script.exists():
        print("⚠️  yo_full_test.sh not found. Please recreate it first.")
        raise SystemExit(1)

    backends = detect_backends()
    verify_namespace = get_config().namespace

    env = dict(os.environ)

    env["YO_HAVE_MILVUS"] = "1" if backends.milvus.available else "0"
    env["YO_MILVUS_REASON"] = backends.milvus.message
    env["YO_SKIP_MILVUS"] = "0" if backends.milvus.available else "1"
    if not backends.milvus.available:
        print(
            "⚠️  Milvus Lite not detected — vector-store operations disabled. "
            f"{backends.milvus.message}"
        )

    env["YO_HAVE_OLLAMA_PY"] = "1" if backends.ollama_python.available else "0"
    env["YO_OLLAMA_PY_REASON"] = backends.ollama_python.message

    env["YO_HAVE_OLLAMA_CLI"] = "1" if backends.ollama_cli.available else "0"
    env["YO_OLLAMA_CLI_REASON"] = backends.ollama_cli.message

    ollama_ready = backends.ollama_python.available and backends.ollama_cli.available
    env["YO_SKIP_OLLAMA"] = "0" if ollama_ready else "1"

    if not ollama_ready:
        print("⚠️  Ollama backend incomplete — generation tests will be skipped.")
        if not backends.ollama_python.available:
            print(f"   • {backends.ollama_python.message}")
        if not backends.ollama_cli.available:
            print(f"   • {backends.ollama_cli.message}")

    pytest_returncode, pytest_metrics, _ = run_pytest_with_metrics(["--disable-warnings"])
    if pytest_returncode != 0:
        print("❌ Pytest reported failures. Aborting verify run.")
        summary = write_test_summary("❌ Pytest failed", namespace=verify_namespace, **pytest_metrics)
        if summary.get("status", "").startswith("✅"):
            _display_verify_banner(summary)
        raise SystemExit(pytest_returncode)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = Path.cwd() / f"yo_test_results_{ts}.log"
    print(f"🧠 Running full Yo test suite… (logging to {logfile.name})")

    env["YO_LOGFILE"] = str(logfile)

    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        env=env,
    )

    if result.returncode == 0:
        print(f"\n✅ Verification complete. Check {logfile.name} for full details.\n")
        summary = write_test_summary(
            "✅ Verify successful",
            logfile=str(logfile),
            namespace=verify_namespace,
            **pytest_metrics,
        )
        _display_verify_banner(summary)
        return

    print(
        f"\n❌ Verification failed with exit code {result.returncode}. "
        f"Review {logfile.name} for details.\n"
    )
    write_test_summary(
        f"❌ Verify failed (exit {result.returncode})",
        logfile=str(logfile),
        namespace=verify_namespace,
        **pytest_metrics,
    )
    raise SystemExit(result.returncode)


def run_doctor(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    """Run a quick environment diagnostic to help with local setup issues."""

    import platform
    import shutil

    def _status_icon(status: Status) -> str:
        return {"ok": "✅", "warn": "⚠️", "fail": "❌"}[status]

    def _report(title: str, status: Status, detail: str = "") -> Status:
        icon = _status_icon(status)
        print(f"{icon} {title}")
        if detail:
            for line in detail.strip().splitlines():
                print(f"   {line}")
        return status

    def _run_check(title: str, check: Callable[[], tuple[Status, str]]) -> Status:
        try:
            status, detail = check()
        except Exception as exc:  # pragma: no cover - defensive guard
            status, detail = "fail", str(exc)
        return _report(title, status, detail)

    def _summarize(statuses: Sequence[Status]) -> Status:
        if any(state == "fail" for state in statuses):
            return "fail"
        if any(state == "warn" for state in statuses):
            return "warn"
        return "ok"

    print("🩺 Yo Doctor — checking your setup\n")

    statuses: list[Status] = []

    def _check_python() -> tuple[Status, str]:
        version = platform.python_version()
        detail = f"Detected Python {version}."
        if sys.version_info < (3, 9):
            return "fail", detail + " Please use Python 3.9 or newer."
        if sys.version_info < (3, 10):
            return "warn", detail + " Consider upgrading to Python 3.10+ for best results."
        return "ok", detail

    def _check_executable(name: str, display: str, extra_hint: str = "") -> tuple[Status, str]:
        path = shutil.which(name)
        if not path:
            hint = extra_hint or f"Install {display} and ensure it is on your PATH."
            return "fail", hint
        try:
            result = subprocess.run(
                [name, "--version"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        except Exception as exc:  # pragma: no cover - safety net
            return "fail", f"Could not execute {display}: {exc}"

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"Exit code {result.returncode}"
            return "fail", message

        version_info = result.stdout.strip() or result.stderr.strip() or "version check succeeded"
        return "ok", f"Found at {path} ({version_info})."

    def _check_module(module: str, hint: str) -> tuple[Status, str]:
        if import_util.find_spec(module) is None:
            return "fail", hint
        return "ok", f"Python module '{module}' is available."

    def _check_distribution(
        dist: str,
        hint: str,
        min_version: str | None = None,
    ) -> tuple[Status, str]:
        try:
            version = importlib_metadata.version(dist)
        except importlib_metadata.PackageNotFoundError:
            return "fail", hint

        detail = f"{dist} {version} detected."
        if not min_version:
            return "ok", detail

        try:
            if Version(version) < Version(min_version):
                return (
                    "fail",
                    f"{dist} {version} found. Upgrade to {min_version}+ via `pip install -U {dist}`.",
                )
        except InvalidVersion:
            return "warn", detail + " (unable to compare versions)"
        return "ok", detail

    statuses.append(_run_check("Python version", _check_python))
    dependency_checks: Sequence[tuple[str, str, str, str | None]] = (
        (
            "langchain version",
            "langchain",
            "Install with: pip install -r requirements.txt",
            None,
        ),
        (
            "langchain-ollama>=0.1.0",
            "langchain-ollama",
            "Install with: pip install 'langchain-ollama>=0.1.0'",
            "0.1.0",
        ),
        (
            "setuptools>=81",
            "setuptools",
            "Install with: pip install -U 'setuptools>=81'",
            "81",
        ),
        (
            "milvus-lite>=2.4.4",
            "milvus-lite",
            "Install with: pip install 'milvus-lite>=2.4.4'",
            "2.4.4",
        ),
    )
    for title, dist, hint, minimum in dependency_checks:
        statuses.append(
            _run_check(
                title,
                lambda dist=dist, hint=hint, minimum=minimum: _check_distribution(
                    dist,
                    hint,
                    min_version=minimum,
                ),
            )
        )
    statuses.append(
        _run_check(
            "Ollama CLI version",
            lambda: _check_executable(
                "ollama",
                "Ollama",
                "Install the Ollama CLI from https://ollama.com/download and ensure it is on your PATH.",
            ),
        )
    )
    statuses.append(
        _run_check(
            "pymilvus installed",
            lambda: _check_module("pymilvus", "Install with: pip install pymilvus[milvus_lite]"),
        )
    )

    backends = detect_backends()
    statuses.append(
        _report(
            "Milvus Lite runtime",
            "ok" if backends.milvus.available else "fail",
            backends.milvus.message,
        )
    )
    statuses.append(
        _report(
            "Ollama Python bindings",
            "ok" if backends.ollama_python.available else "fail",
            backends.ollama_python.message,
        )
    )
    statuses.append(
        _report(
            "Ollama CLI detected",
            "ok" if backends.ollama_cli.available else "fail",
            backends.ollama_cli.message,
        )
    )

    data_dir = Path("data")
    statuses.append(
        _report(
            "Data directory present",
            "ok" if data_dir.exists() else "fail",
            "Run `mkdir data` in the project root." if not data_dir.exists() else f"Using {data_dir.resolve()}",
        )
    )

    test_script = Path("yo_full_test.sh")
    statuses.append(
        _report(
            "Regression script available",
            "ok" if test_script.exists() else "fail",
            "Restore yo_full_test.sh from the repo root." if not test_script.exists() else "Found in project root.",
        )
    )

    def _check_brain() -> tuple[Status, str]:
        try:
            YoBrain()
        except Exception as exc:  # pragma: no cover - best effort diagnosis
            return "fail", f"{exc}\nInstall missing dependencies or check Milvus Lite permissions."
        return "ok", "Milvus Lite connection established."

    statuses.append(_run_check("YoBrain initialization", _check_brain))

    summary = _summarize(statuses)
    if summary == "ok":
        print("\n✅ Everything looks ready! Try `python3 -m yo.cli verify` next.")
    elif summary == "warn":
        print("\n⚠️ Resolve the warnings above before continuing.")
    else:
        print("\n❌ Fix the items marked above, then rerun `python3 -m yo.cli doctor`.")


def _handle_add(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    try:
        brain.ingest(args.path, namespace=args.ns)
    except FileNotFoundError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc
    except MissingDependencyError as exc:
        print(f"❌ {exc}")
        print("   Install the missing dependency and retry.")
        raise SystemExit(1) from exc
    except IngestionError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc


def _handle_ask(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    namespace = args.ns or getattr(brain, "active_namespace", _active_namespace_default()) or _active_namespace_default()

    if getattr(args, "debug", False):
        timeout = getattr(args, "timeout", None)
        effective_timeout = timeout if timeout is not None else float(os.environ.get("YO_CHAT_TIMEOUT", 10.0))
        print(
            f"[CHAT TIMING] start namespace={namespace} model={getattr(brain, 'model_name', 'unknown')} "
            f"timeout={effective_timeout:.1f}s"
        )

        async def _run_chat() -> dict[str, Any]:
            return await brain.chat_async(
                message=args.question,
                namespace=namespace,
                history=None,
                web=args.web,
                timeout=effective_timeout,
            )

        start = time.perf_counter()
        payload = asyncio.run(_run_chat())
        elapsed = time.perf_counter() - start
        text = ""
        if isinstance(payload, dict):
            text = str(payload.get("text") or payload.get("response") or "")
        else:
            text = str(payload or "")
        text = text.strip()
        print(
            f"[CHAT TIMING] finished elapsed={elapsed:.2f}s text_len={len(text)} "
            f"fallback={payload.get('fallback_used') if isinstance(payload, dict) else 'n/a'}"
        )
        print("\n💬 Yo says:\n")
        print(text or "(no text)")
        return

    brain.ask(args.question, namespace=namespace, web=args.web)


def _handle_summarize(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain.summarize(namespace=args.ns)


def _handle_ns_list(_: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain.ns_list()


def _handle_ns_switch(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    target = _resolve_namespace_arg(args)
    brain.ns_switch(target)


def _handle_ns_purge(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    target = _resolve_namespace_arg(args)
    brain.ns_purge(target)


def _handle_ns_stats(_: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None

    metrics = brain.namespace_activity()
    if not metrics:
        print("ℹ️  No namespaces available.")
        return

    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    alerts: list[str] = []

    for name, data in sorted(metrics.items()):
        documents = int(data.get("documents", 0) or 0)
        documents_delta = int(data.get("documents_delta", 0) or 0)
        chunks = int(data.get("chunks", 0) or 0)
        chunks_delta = int(data.get("chunks_delta", 0) or 0)
        records = data.get("records")
        growth_percent = float(data.get("growth_percent", 0.0) or 0.0)
        ingest_runs = int(data.get("ingest_runs", 0) or 0)
        last_ingested = _format_timestamp(data.get("last_ingested"))

        rows.append(
            (
                name,
                f"{documents:,}",
                f"+{documents_delta}" if documents_delta else "0",
                f"{chunks:,}",
                f"+{chunks_delta}" if chunks_delta else "0",
                f"{records:,}" if isinstance(records, int) else "n/a",
                f"{growth_percent:.1f}%",
                str(ingest_runs),
                last_ingested,
            )
        )

        if documents > NAMESPACE_DOCUMENT_ALERT:
            alerts.append(f"{name}: {documents} documents exceeds {NAMESPACE_DOCUMENT_ALERT}")
        if chunks > NAMESPACE_CHUNK_ALERT:
            alerts.append(f"{name}: {chunks} chunks exceeds {NAMESPACE_CHUNK_ALERT}")
        if growth_percent > NAMESPACE_GROWTH_ALERT:
            alerts.append(f"{name}: growth {growth_percent:.1f}% exceeds threshold")

    if console and Table:
        table = Table(title="Namespace Statistics")
        table.add_column("Namespace", style="cyan")
        table.add_column("Documents", justify="right")
        table.add_column("Δ Docs", justify="right")
        table.add_column("Chunks", justify="right")
        table.add_column("Δ Chunks", justify="right")
        table.add_column("Records", justify="right")
        table.add_column("Growth", justify="right")
        table.add_column("Ingests", justify="right")
        table.add_column("Last Ingested", justify="left")
        for row in rows:
            table.add_row(*row)
        console.print(table)
    else:
        print("Namespace Statistics:")
        for row in rows:
            print(
                f" - {row[0]}: docs={row[1]} (Δ {row[2]}), chunks={row[3]} (Δ {row[4]}), records={row[5]}, growth={row[6]}, ingests={row[7]}, last={row[8]}"
            )

    if alerts:
        _rich_print("\n⚠️  Alerts:", style="yellow")
        for alert in alerts:
            _rich_print(f" - {alert}", style="yellow")


def _handle_ns_drift(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None

    try:
        window = _parse_since(getattr(args, "since", None))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    metrics = brain.namespace_drift(window)
    if not metrics:
        print("ℹ️  No namespaces available.")
        return

    rows: list[tuple[str, str, str, str, str, str, str]] = []
    for name, data in sorted(metrics.items()):
        documents_added = int(data.get("documents_added", 0) or 0)
        chunks_added = int(data.get("chunks_added", 0) or 0)
        growth_percent = float(data.get("growth_percent", 0.0) or 0.0)
        ingests = int(data.get("ingests", 0) or 0)
        records = data.get("records")
        last_ingested = _format_timestamp(data.get("last_ingested"))
        rows.append(
            (
                name,
                f"+{documents_added}" if documents_added else "0",
                f"+{chunks_added}" if chunks_added else "0",
                f"{growth_percent:.1f}%",
                str(ingests),
                f"{records:,}" if isinstance(records, int) else "n/a",
                last_ingested,
            )
        )

    window_label = getattr(args, "since", None) or DEFAULT_DRIFT_WINDOW
    if console and Table:
        table = Table(title=f"Namespace Drift — last {window_label}")
        table.add_column("Namespace", style="cyan")
        table.add_column("Δ Docs", justify="right")
        table.add_column("Δ Chunks", justify="right")
        table.add_column("Growth", justify="right")
        table.add_column("Ingests", justify="right")
        table.add_column("Records", justify="right")
        table.add_column("Last Ingested", justify="left")
        for row in rows:
            table.add_row(*row)
        console.print(table)
    else:
        print(f"Namespace Drift (last {window_label}):")
        for row in rows:
            print(
                f" - {row[0]}: Δdocs={row[1]}, Δchunks={row[2]}, growth={row[3]}, ingests={row[4]}, records={row[5]}, last={row[6]}"
            )


def _handle_cache_list(_: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain._list_cache()


def _handle_cache_clear(_: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain._clear_cache()


def _handle_compact(_: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain.compact()


def _handle_config_view(args: argparse.Namespace, _: YoBrain | None = None) -> None:
    cli_args = {}
    if getattr(args, "ns", None):
        cli_args["namespace"] = args.ns
    config = get_config(cli_args=cli_args or None)
    print(json.dumps(serialize_config(config), indent=2))


def _handle_config_set(args: argparse.Namespace, _: YoBrain | None = None) -> None:
    try:
        update_config_value(
            args.key,
            args.value,
            namespace=getattr(args, "ns", None),
            data_dir=get_config().data_dir,
        )
    except ValueError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc
    target = f"namespace '{args.ns}'" if getattr(args, "ns", None) else "global config"
    print(f"✅ Updated {target}: {args.key} → {args.value}")


def _handle_config_reset(args: argparse.Namespace, _: YoBrain | None = None) -> None:
    keys = [args.key] if args.key else None
    reset_config(
        keys,
        namespace=getattr(args, "ns", None),
        data_dir=get_config().data_dir,
    )
    scope = f"namespace '{args.ns}'" if getattr(args, "ns", None) else "global config"
    detail = args.key if args.key else "all configurable keys"
    print(f"✅ Reset {detail} for {scope}.")


def _handle_config_edit(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    editor = os.environ.get("EDITOR")
    if not editor:
        for candidate in ("nano", "vim", "vi"):
            if shutil.which(candidate):
                editor = candidate
                break
        if not editor:
            raise SystemExit("Set the $EDITOR environment variable to edit configuration.")

    env_path = ENV_FILE
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.touch(exist_ok=True)

    try:
        subprocess.run([editor, str(env_path)], check=False)
    except FileNotFoundError as exc:
        raise SystemExit(f"Editor '{editor}' not found.") from exc


def _handle_help(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    topic = args.topic
    if topic:
        entry = COMMAND_REGISTRY.get(topic)
        if entry is None and topic in COMMAND_REGISTRY:
            entry = COMMAND_REGISTRY[topic]
        if entry is None:
            _rich_print(
                f"ℹ️  Unknown command '{topic}'. Run `yo help` to list available commands.",
                style="yellow",
            )
            return
        if not entry.get("primary", True) and entry.get("alias_of"):
            entry = COMMAND_REGISTRY.get(entry["alias_of"], entry)
        parser = entry.get("parser")
        if parser is None:
            _rich_print("ℹ️  Detailed help unavailable for this command.", style="yellow")
            return
        help_text = parser.format_help()
        title = f"`yo {entry['name']}`"
        if console and Panel and Text:
            panel = Panel.fit(Text(help_text), title=title, border_style="cyan")
            console.print(panel)
        else:
            print(help_text)

        subcommands: Dict[str, argparse.ArgumentParser] = {}
        for action in parser._actions:  # type: ignore[attr-defined]
            if isinstance(action, argparse._SubParsersAction):
                subcommands.update(action.choices)
        if subcommands:
            if console and Table:
                table = Table(title="Subcommands", show_lines=False)
                table.add_column("Command")
                table.add_column("Description")
                for sub_name, sub_parser in subcommands.items():
                    meta = COMMAND_REGISTRY.get(sub_name, {})
                    description = (
                        meta.get("help")
                        or sub_parser.description
                        or sub_parser.format_help().splitlines()[0]
                    )
                    table.add_row(sub_name, description.strip())
                console.print(table)
            else:
                print("\nSubcommands:")
                for sub_name, sub_parser in subcommands.items():
                    meta = COMMAND_REGISTRY.get(sub_name, {})
                    description = meta.get("help") or sub_parser.description or ""
                    print(f" - {sub_name}: {description}")
        return

    sections: Dict[str, list[tuple[str, str]]] = {}
    for info in COMMAND_REGISTRY.values():
        if not info.get("primary", True):
            continue
        if info.get("parent"):
            continue
        name = info["name"]
        help_text = info.get("help") or ""
        category = info.get("category") or "General"
        sections.setdefault(category, []).append((name, help_text))

    if console and Table:
        table = Table(title="Yo Commands", show_lines=False)
        table.add_column("Category", style="cyan")
        table.add_column("Command", style="white")
        table.add_column("Description", style="green")
        for category, items in sorted(sections.items()):
            for idx, (name, help_text) in enumerate(sorted(items)):
                table.add_row(category if idx == 0 else "", name, help_text)
        console.print(table)
    else:
        print("Yo Commands:")
        for category, items in sorted(sections.items()):
            print(f"\n[{category}]")
            for name, help_text in sorted(items):
                print(f" - {name}: {help_text}")
    _rich_print("\nHint: Run `yo help <command>` for detailed usage.", style="cyan")


def _handle_deps_check(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    deps_check_command()


def _handle_deps_repair(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    deps_repair_command()


def _handle_deps_freeze(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    deps_freeze_command()


def _handle_deps_diff(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    deps_diff_command()


def _handle_deps_sync(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    result = deps_sync_command()
    if result != 0:
        raise SystemExit(result)


def _handle_telemetry_report(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    entries = load_test_history()
    if not entries:
        print("ℹ️  No telemetry data recorded yet. Run `python3 -m yo.cli verify` first.")
        return

    last = entries[-1]
    timestamp_str = last.get("timestamp")
    try:
        timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else None
    except ValueError:
        timestamp = None

    status = last.get("status", "(unknown)")
    total_runs = len(entries)

    durations = [entry.get("duration_seconds") for entry in entries if isinstance(entry.get("duration_seconds"), (int, float))]
    average_duration = mean(durations) if durations else None

    successful_runs = sum(
        1
        for entry in entries
        if str(entry.get("status", "")).startswith("✅") and (entry.get("tests_failed", 0) in (0, None))
    )
    pass_rate = (successful_runs / total_runs * 100) if total_runs else 0.0

    print("📊 Yo Telemetry Report\n")
    if timestamp:
        print(f"Last run: {status} at {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print(f"Last run: {status}")
    print(f"Total runs logged: {total_runs}")
    if average_duration is not None:
        print(f"Average duration: {average_duration:.2f}s")
    else:
        print("Average duration: n/a")
    print(f"Pass rate: {pass_rate:.1f}%")


def _handle_telemetry_analyze(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    summary = build_telemetry_summary()
    if not summary:
        print("ℹ️  No telemetry data available yet. Run `python3 -m yo.cli verify` first.")
        return

    latest = summary.get("latest", {})
    pass_rate_mean = summary.get("pass_rate_mean")
    volatility = summary.get("pass_rate_volatility")
    duration_avg = summary.get("duration_average")
    recurring_errors = summary.get("recurring_errors", [])

    version = summary.get("version")
    commit = summary.get("commit")
    health_score = summary.get("health_score")

    if getattr(args, "json", False):
        payload = {
            "latest": latest,
            "pass_rate_mean": pass_rate_mean,
            "pass_rate_volatility": volatility,
            "duration_average": duration_avg,
            "recurring_errors": recurring_errors,
            "daily_stats": summary.get("daily_stats", []),
            "version": version,
            "commit": commit,
            "health_score": health_score,
        }
        print(json.dumps(payload, indent=2))
        return

    def _arrow(delta: float | None) -> str:
        if delta is None:
            return ""
        if delta > 0:
            return "↑"
        if delta < 0:
            return "↓"
        return "→"

    history = load_test_history()
    trend = compute_trend(history, days=2)
    recent_rates = [entry.get("pass_rate_percent") for entry in trend if entry.get("pass_rate_percent") is not None]
    delta = None
    if len(recent_rates) >= 2:
        delta = recent_rates[-1] - recent_rates[-2]

    print("📈 Yo Telemetry Analysis\n")
    if latest:
        print(
            f"Latest status: {latest.get('status')} ({latest.get('tests_passed', 0)}/{latest.get('tests_total', 0)} passed, {latest.get('duration_seconds')}s)"
        )
    if pass_rate_mean is not None:
        arrow = _arrow(delta)
        rate_display = pass_rate_mean * 100 if pass_rate_mean <= 1 else pass_rate_mean
        print(f"Pass rate (avg): {rate_display:.1f}% {arrow}")
    if volatility is not None:
        print(f"Pass rate volatility: {volatility:.3f}")
    if duration_avg is not None:
        print(f"Average runtime: {duration_avg:.2f}s")

    if recurring_errors:
        print("\nTop recurring issues:")
        for issue in recurring_errors:
            print(f"   • {issue['message']} ({issue['count']}x)")
    else:
        print("\nTop recurring issues: none detected")

    if summary.get("daily_stats"):
        print("\nDaily overview (recent):")
        for entry in summary["daily_stats"][:7]:
            rate = entry.get("pass_rate")
            rate_display = f"{rate * 100:.1f}%" if isinstance(rate, (int, float)) else "n/a"
            duration = entry.get("duration_seconds")
            duration_display = f"{duration:.2f}s" if isinstance(duration, (int, float)) else "n/a"
            print(
                f"   • {entry['day']}: {entry['runs']} runs, pass rate {rate_display}, avg duration {duration_display}"
            )

    if getattr(args, "release", False):
        print("\nRelease context:")
        print(f"   • Version: {version or 'unknown'}")
        print(f"   • Commit: {commit or 'unknown'}")
        if isinstance(health_score, (int, float)):
            print(f"   • Health score: {health_score:.1f}")
        else:
            print("   • Health score: unavailable")


def _handle_telemetry_archive(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    path = archive_telemetry()
    if path:
        print(f"✅ Archived telemetry to {path}")
    else:
        print("ℹ️  No telemetry data available to archive.")


def _handle_telemetry_archives_list(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    limit = getattr(args, "limit", None)
    archives = list_archives(limit=limit)
    if not archives:
        print("ℹ️  No telemetry archives found.")
        return

    print("🗂️  Telemetry archives:")
    for entry in archives:
        print(f"   • {entry}")


def _handle_telemetry_trace(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    session_id = getattr(args, "session", "").strip()
    if not session_id:
        print("❌ --session is required for telemetry trace.")
        raise SystemExit(1)

    log_path = CHAT_TIMING_JSONL if CHAT_TIMING_JSONL.exists() else CHAT_TIMING_LOG
    entries: list[dict[str, Any]] = []
    if log_path.exists():
        with log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("session_id") == session_id:
                    entries.append(payload)

    if not entries:
        print(f"ℹ️  No chat timing entries recorded for session {session_id}.")
    else:
        entries.sort(key=lambda entry: _parse_iso8601(entry.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
        base_ts = _parse_iso8601(entries[0].get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc)
        print("t0_ms,event_type,latency_ms,success,text_len,error")
        for entry in entries:
            ts = _parse_iso8601(entry.get("timestamp"))
            delta_ms = 0.0
            if ts:
                delta_ms = (ts - base_ts).total_seconds() * 1000.0
            event_type = entry.get("event_type") or entry.get("event") or "unknown"
            latency = entry.get("latency_ms")
            if latency is None and "elapsed_ms" in entry:
                latency = entry.get("elapsed_ms")
            success = entry.get("success")
            text_len = entry.get("text_len")
            if text_len is None:
                text_len = _extract_text_length(entry)
            error = entry.get("error", "")
            latency_str = "" if latency is None else f"{latency}"
            success_str = "" if success is None else str(success)
            text_len_str = "" if text_len is None else str(text_len)
            print(f"{delta_ms:.1f},{event_type},{latency_str},{success_str},{text_len_str},{error}")

    if WS_ERROR_LOG.exists():
        matched_errors = []
        with WS_ERROR_LOG.open("r", encoding="utf-8") as handle:
            for line in handle:
                if session_id in line:
                    matched_errors.append(line.strip())
        if matched_errors:
            print("\nws_errors:")
            for line in matched_errors:
                print(f"  {line}")


def _run_health_monitor(json_output: bool) -> None:
    now = datetime.now(timezone.utc)
    summary = load_test_summary()
    telemetry_summary = load_telemetry_summary() or build_telemetry_summary()

    result: Dict[str, Any] = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "status": "ok",
        "summary_timestamp": None,
        "hours_since_last_run": None,
        "pass_rate": None,
        "health_score": telemetry_summary.get("health_score") if telemetry_summary else None,
        "latest_status": None,
        "reasons": [],
    }

    status: Status = "ok"
    reasons: list[str] = []

    if not summary:
        status = "fail"
        reasons.append("No verification summary found.")
    else:
        summary_timestamp = summary.get("timestamp")
        result["summary_timestamp"] = summary_timestamp
        parsed_ts = _parse_iso8601(summary_timestamp) if isinstance(summary_timestamp, str) else None
        if parsed_ts:
            age_hours = (now - parsed_ts).total_seconds() / 3600
            result["hours_since_last_run"] = round(age_hours, 2)
            if age_hours > 24:
                status = "fail"
                reasons.append("Last verification run is more than 24 hours old.")
            elif age_hours > 12 and status != "fail":
                status = "warn"
                reasons.append("Last verification run is over 12 hours old.")
        else:
            status = "warn"
            reasons.append("Latest verification timestamp is missing or invalid.")

        latest_status = summary.get("status")
        if latest_status is not None:
            result["latest_status"] = latest_status
            if isinstance(latest_status, str) and not latest_status.startswith("✅"):
                status = "fail"
                reasons.append(f"Latest run reported: {latest_status}")

        pass_rate_raw = summary.get("pass_rate")
        if isinstance(pass_rate_raw, (int, float)):
            pass_rate_pct = pass_rate_raw * 100 if pass_rate_raw <= 1 else pass_rate_raw
            result["pass_rate"] = round(pass_rate_pct, 2)
            if pass_rate_pct < 95:
                status = "fail"
                reasons.append(f"Pass rate below threshold ({pass_rate_pct:.1f}%).")
        else:
            reasons.append("Pass rate unavailable.")
            if status == "ok":
                status = "warn"

    if telemetry_summary and isinstance(telemetry_summary, dict):
        generated_at = telemetry_summary.get("generated_at")
        if generated_at:
            result["telemetry_generated_at"] = generated_at

    result["status"] = status
    result["reasons"] = reasons or ["All checks passed."]

    logs_dir = Path("data/logs")
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    monitor_path = logs_dir / "health_monitor.jsonl"
    try:
        with monitor_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result) + "\n")
    except OSError:
        pass
    result["log_path"] = str(monitor_path)

    metrics_snapshot = summarize_since("7d")
    ws_stats = (metrics_snapshot.get("types") or {}).get("ws_success_rate", {})
    ws_field = (ws_stats.get("fields") or {}).get("value") or {}
    ws_rate = ws_field.get("avg")
    result["ws_success_rate"] = ws_rate
    chat_page_stats = (metrics_snapshot.get("types") or {}).get("chat_get", {})
    chat_page_fields = chat_page_stats.get("fields", {})
    chat_page_elapsed = (chat_page_fields.get("elapsed_ms") or {})
    chat_page_avg = chat_page_elapsed.get("avg")
    chat_page_max = chat_page_elapsed.get("max")
    if chat_page_avg is not None:
        result["chat_page_avg_ms"] = chat_page_avg
    if chat_page_max is not None:
        result["chat_page_max_ms"] = chat_page_max
    chat_stats = (metrics_snapshot.get("types") or {}).get("chat", {})
    chat_fields = chat_stats.get("fields", {})
    fallback_avg = (chat_fields.get("fallback") or {}).get("avg")
    first_token_avg = (chat_fields.get("first_token_latency_ms") or {}).get("avg")
    if fallback_avg is not None:
        result["chat_fallback_rate"] = fallback_avg
    if first_token_avg is not None:
        result["first_token_latency_ms"] = first_token_avg
    if ws_rate is not None:
        if ws_rate < 95:
            status = "fail"
            reasons.append(f"WebSocket success rate below threshold ({ws_rate:.1f}%).")
        elif ws_rate < 98 and status == "ok":
            status = "warn"
            reasons.append(f"WebSocket success rate trending down ({ws_rate:.1f}%).")

    if fallback_avg is not None:
        result["chat_fallback_rate"] = fallback_avg
        if fallback_avg > 0.25:
            status = "fail"
            reasons.append(f"Fallback usage too high ({fallback_avg * 100:.1f}% of chats).")
        elif fallback_avg > 0.1 and status == "ok":
            status = "warn"
            reasons.append(f"Fallback usage elevated ({fallback_avg * 100:.1f}% of chats).")
    if chat_page_max is not None and chat_page_max > CHAT_PAGE_WARN_THRESHOLD_MS:
        if chat_page_max > CHAT_PAGE_WARN_THRESHOLD_MS * 1.5:
            status = "fail"
        elif status == "ok":
            status = "warn"
        reasons.append(
            f"/chat load time high ({chat_page_max:.1f}ms > {CHAT_PAGE_WARN_THRESHOLD_MS:.0f}ms)"
        )
    if first_token_avg is not None:
        result["first_token_latency_ms"] = first_token_avg

    result["status"] = status

    record_metric(
        "health",
        status=status,
        pass_rate=result.get("pass_rate"),
        hours_since_last_run=result.get("hours_since_last_run"),
        health_score=result.get("health_score"),
    )

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(f"🩺 Health monitor status: {status.upper()}")
        for reason in result["reasons"]:
            print(f"   • {reason}")
        if result.get("pass_rate") is not None:
            print(f"   • Pass rate: {result['pass_rate']:.2f}%")
        if result.get("hours_since_last_run") is not None:
            print(f"   • Hours since last run: {result['hours_since_last_run']:.2f}")
        if result.get("health_score") is not None:
            print(f"   • Health score: {result['health_score']}")

    if status == "fail":
        raise SystemExit(1)


def _handle_health_report(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    action = getattr(args, "action", "report") or "report"
    if action == "monitor":
        _run_health_monitor(getattr(args, "json", False))
        return
    if action == "web":
        _handle_health_web(args, None)
        return
    if action == "chat":
        _handle_health_chat(args, None)
        return
    if action == "ws":
        _handle_health_ws(args, None)
        return
    if action != "report":
        raise SystemExit(f"Unknown health action '{action}'. Try `yo health report`.")

    telemetry_summary = load_telemetry_summary() or build_telemetry_summary()
    history = load_test_history()

    if not telemetry_summary and not history:
        print("ℹ️  No telemetry available. Run `python3 -m yo.cli verify` first.")
        return

    score = compute_health_score(history, telemetry_summary)
    latest = telemetry_summary.get("latest", {}) if telemetry_summary else {}
    recurring = telemetry_summary.get("recurring_errors", []) if telemetry_summary else []
    dependency_events = load_dependency_history(limit=10)

    payload = {
        "health_score": score,
        "latest": latest,
        "recurring_errors": recurring,
        "dependency_events": dependency_events,
    }

    recommendations = generate_recommendations()
    payload["recommendations"] = recommendations

    metrics_snapshot = summarize_since("7d")
    ws_stats = (metrics_snapshot.get("types") or {}).get("ws_success_rate", {})
    ws_field = (ws_stats.get("fields") or {}).get("value") or {}
    ws_rate = ws_field.get("avg")
    payload["ws_success_rate"] = ws_rate

    chat_page_stats = (metrics_snapshot.get("types") or {}).get("chat_get", {})
    chat_page_fields = chat_page_stats.get("fields", {})
    chat_page_elapsed = chat_page_fields.get("elapsed_ms") or {}
    chat_page_avg = chat_page_elapsed.get("avg")
    chat_page_max = chat_page_elapsed.get("max")
    payload["chat_page_avg_ms"] = chat_page_avg
    payload["chat_page_max_ms"] = chat_page_max

    chat_stats = (metrics_snapshot.get("types") or {}).get("chat", {})
    chat_fields = chat_stats.get("fields", {})
    fallback_avg = (chat_fields.get("fallback") or {}).get("avg")
    first_token_avg = (chat_fields.get("first_token_latency_ms") or {}).get("avg")
    payload["chat_fallback_rate"] = fallback_avg
    payload["first_token_latency_ms"] = first_token_avg

    if ws_rate is not None and ws_rate < 95:
        payload.setdefault("alerts", []).append(f"WebSocket success rate {ws_rate:.1f}%")
    if fallback_avg is not None and fallback_avg > 0.1:
        payload.setdefault("alerts", []).append(f"Fallback usage {fallback_avg * 100:.1f}%")
    if chat_page_max is not None and chat_page_max > CHAT_PAGE_WARN_THRESHOLD_MS:
        payload.setdefault("alerts", []).append(
            f"/chat max load time {chat_page_max:.1f}ms exceeds {CHAT_PAGE_WARN_THRESHOLD_MS:.0f}ms"
        )

    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return

    print("💚 Yo Health Report\n")
    print(f"Overall health score: {score:.1f}/100")
    if chat_page_avg is not None:
        max_display = f", max {chat_page_max:.1f}ms" if chat_page_max is not None else ""
        print(f"/chat load time avg: {chat_page_avg:.1f}ms{max_display}")

    if latest:
        print(
            "Latest run: {status} ({passed}/{total} passed, {duration}s)".format(
                status=latest.get("status", "unknown"),
                passed=latest.get("tests_passed", 0),
                total=latest.get("tests_total", 0),
                duration=latest.get("duration_seconds", "n/a"),
            )
        )
    else:
        print("Latest run: unavailable")

    if recurring:
        print("\nRecurring issues:")
        for issue in recurring[:5]:
            print(f"   • {issue['message']} ({issue['count']}x)")
    else:
        print("\nRecurring issues: none detected")

    if dependency_events:
        print("\nRecent dependency activity:")
        for event in dependency_events[:5]:
            packages = ", ".join(event.get("packages", [])) or "n/a"
            print(f"   • {event.get('timestamp')}: {event.get('action')} ({packages})")
    else:
        print("\nRecent dependency activity: none recorded")

    if recommendations:
        print("\nOptimisation suggestions:")
        for rec in recommendations[:3]:
            title = rec.get("title", rec.get("id", "recommendation"))
            detail = rec.get("detail")
            print(f"   • {title}")
            if detail:
                print(f"     {detail}")
    else:
        print("\nOptimisation suggestions: none")

    if ws_rate is not None:
        print(f"\nWebSocket success rate (7d): {ws_rate:.1f}%")
        if ws_rate < 95:
            print("   ⚠️  Below target. Inspect `yo logs tail --ws` for details.")
    if fallback_avg is not None:
        print(f"Chat fallback usage (7d): {fallback_avg * 100:.1f}%")
    if first_token_avg is not None:
        print(f"First-token latency avg: {first_token_avg:.1f} ms")


def _handle_explain_verify(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    summary = load_test_summary()
    history = load_test_history()
    dependency_history = load_dependency_history(limit=10)
    telemetry_summary = load_telemetry_summary() or build_telemetry_summary()

    if not summary:
        print("ℹ️  No verification telemetry available. Run `python3 -m yo.cli verify` first.")
        return

    status = summary.get("status", "unknown")
    print("🧠 Yo Verify Insight\n")
    print(f"Current status: {status}")

    tests_total = summary.get("tests_total")
    tests_failed = summary.get("tests_failed")
    duration = summary.get("duration_seconds")
    if tests_total is not None:
        print(f"Tests: {summary.get('tests_passed', 0)}/{tests_total} passed")
    if duration is not None:
        print(f"Duration: {float(duration):.2f}s")

    missing_modules = summary.get("missing_modules") or []
    payload = {
        "status": status,
        "tests_total": tests_total,
        "tests_failed": tests_failed,
        "duration_seconds": duration,
        "missing_modules": missing_modules,
        "telemetry": telemetry_summary,
    }

    compact = getattr(args, "compact", False)
    if compact:
        line = f"{status} — {summary.get('tests_passed', 0)}/{tests_total or 0} passed"
        if duration is not None:
            line += f" in {float(duration):.2f}s"
        if missing_modules:
            line += f"; missing modules: {', '.join(missing_modules)}"
        elif tests_failed:
            line += "; see log for failures"
        else:
            line += "; no failures detected"
        print(line)
        return

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    if missing_modules:
        print("\n⚠️  Missing modules detected:")
        for module in missing_modules:
            print(f"   • {module}")
    elif tests_failed:
        print("\n⚠️  Failures detected. See log for more detail.")
    else:
        print("\n✅ No missing modules or failures in latest run.")

    failure_summary = summarize_failures(history, window=5)
    recent_failures = failure_summary.get("recent_failures", [])
    if recent_failures:
        print("\n🔍 Recent failure details:")
        for entry in recent_failures:
            ts = entry.get("timestamp")
            status_line = entry.get("status", "unknown")
            print(f"   • {ts}: {status_line} (failed tests: {entry.get('tests_failed', 0)})")

    recent_missing = failure_summary.get("missing_modules", [])
    if recent_missing:
        print("\n🧩 Recurring missing modules: " + ", ".join(recent_missing))

    if dependency_history and (missing_modules or recent_missing) and not compact:
        print("\n🛠  Recent dependency activity:")
        for event in dependency_history[-5:]:
            timestamp = event.get("timestamp")
            action = event.get("action")
            packages = ", ".join(event.get("packages", []))
            print(f"   • {timestamp}: {action} ({packages})")

    if missing_modules:
        print("\n💡 Suggested action: run `python3 -m yo.cli deps repair` to attempt automatic installation.")

    metrics = telemetry_summary or {}
    if metrics and not compact:
        mean_rate = metrics.get("pass_rate_mean")
        volatility = metrics.get("pass_rate_volatility")
        duration_avg = metrics.get("duration_average")
        if mean_rate is not None:
            display_rate = mean_rate * 100 if mean_rate <= 1 else mean_rate
            print(f"\n📈 Avg pass rate (last runs): {display_rate:.1f}%")
        if volatility is not None:
            print(f"📉 Pass-rate volatility: {volatility:.3f}")
        if duration_avg is not None:
            print(f"⏱️  Average runtime: {duration_avg:.2f}s")

    if getattr(args, "web", False):
        try:
            import requests  # type: ignore
        except ImportError:
            print("\n🌐 --web requested but the 'requests' package is not installed.")
        else:
            for module in missing_modules[:3]:
                package = module.replace("_", "-")
                url = f"https://pypi.org/pypi/{package}/json"
                try:
                    resp = requests.get(url, timeout=5)
                except Exception as exc:  # pragma: no cover - network failure path
                    print(f"\n🌐 Unable to fetch metadata for {package}: {exc}")
                    continue
                if resp.status_code == 200:
                    info = resp.json().get("info", {})
                    summary_text = info.get("summary") or info.get("description") or "No summary available."
                    snippet = summary_text.strip().replace("\n", " ")
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "..."
                    print(f"\n🌐 {package}: {snippet}")
                else:
                    print(f"\n🌐 Unable to fetch metadata for {package} (HTTP {resp.status_code}).")


def _handle_dashboard_cli(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    def _render(clear: bool = False) -> None:
        summary = load_test_summary()
        history = load_test_history(limit=10)
        dependency_history = load_dependency_history(limit=5)
        trend = compute_trend(history, days=7)
        telemetry_summary = load_telemetry_summary() or build_telemetry_summary()
        health_score = compute_health_score(history, telemetry_summary)
        ledger_entry: Dict[str, Any] | None = None
        ledger_path = Path("data/logs/verification_ledger.jsonl")
        if ledger_path.exists():
            try:
                ledger_lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if ledger_lines:
                    ledger_entry = json.loads(ledger_lines[-1])
            except json.JSONDecodeError:
                ledger_entry = None
        checksum_file_path = Path("data/logs/checksums/artifact_hashes.txt")
        signature_path = Path("data/logs/checksums/artifact_hashes.sig")

        if clear:
            if console:
                console.clear()
            else:
                os.system("cls" if os.name == "nt" else "clear")

        print("🖥️  Yo Developer Dashboard\n")

        if summary:
            print("Latest Verification:")
            print(f"   Status: {summary.get('status', 'unknown')}")
            print(
                "   Tests: {} passed / {} total".format(
                    summary.get("tests_passed", 0), summary.get("tests_total", 0)
                )
            )
            duration = summary.get("duration_seconds")
            if duration is not None:
                print(f"   Duration: {float(duration):.2f}s")
            print(f"   Logged at: {summary.get('timestamp', 'unknown')}")
        else:
            print("Latest Verification: unavailable")

        if trend:
            print("\nRecent Trend (last {} runs):".format(len(trend)))
            for entry in trend:
                ts = entry.get("timestamp")
                status = entry.get("status")
                failures = entry.get("tests_failed", 0)
                duration = entry.get("duration_seconds")
                pass_rate = entry.get("pass_rate_percent")
                line = f"   • {ts} — {status}".strip()
                if failures:
                    line += f" (failures: {failures})"
                if duration is not None:
                    line += f", {float(duration):.2f}s"
                if pass_rate is not None:
                    line += f", pass rate: {pass_rate:.1f}%"
                print(line)
        else:
            print("\nRecent Trend: unavailable")

        if dependency_history:
            print("\nDependency Events:")
            for event in dependency_history:
                timestamp = event.get("timestamp")
                action = event.get("action")
                packages = ", ".join(event.get("packages", []))
                print(f"   • {timestamp}: {action} ({packages})")
        else:
            print("\nDependency Events: none recorded")

        if telemetry_summary:
            mean_rate = telemetry_summary.get("pass_rate_mean")
            volatility = telemetry_summary.get("pass_rate_volatility")
            duration_avg = telemetry_summary.get("duration_average")
            print("\nTelemetry Insights:")
            if mean_rate is not None:
                display_rate = mean_rate * 100 if mean_rate <= 1 else mean_rate
                print(f"   • Avg pass rate: {display_rate:.1f}%")
            if volatility is not None:
                print(f"   • Pass-rate volatility: {volatility:.3f}")
            if duration_avg is not None:
                print(f"   • Avg duration: {duration_avg:.2f}s")
            recurring = telemetry_summary.get("recurring_errors") or []
            if recurring:
                print("   • Top recurring issues:")
                for issue in recurring:
                    print(f"     - {issue['message']} ({issue['count']}x)")

        if health_score is not None:
            print(f"\nOverall health score: {health_score:.1f}/100")

        if ledger_entry:
            print("\nSigned Verification:")
            print(f"   • Version: {ledger_entry.get('version', 'unknown')}")
            print(f"   • Commit: {ledger_entry.get('commit', 'unknown')}")
            print(f"   • Health: {ledger_entry.get('health', 'n/a')}")
            print(f"   • Checksum: {ledger_entry.get('checksum_file', checksum_file_path)}")
            signature_display = str(signature_path) if signature_path.exists() else ledger_entry.get("signature", "n/a")
            print(f"   • Signature: {signature_display}")

    def _tail_events() -> None:
        event_log = Path("data/logs/events.jsonl")
        event_log.parent.mkdir(parents=True, exist_ok=True)
        event_log.touch(exist_ok=True)
        print("\n📨 Live events — press Ctrl+C to exit.")
        with event_log.open("r", encoding="utf-8") as fh:
            fh.seek(0, os.SEEK_END)
            try:
                while True:
                    line = fh.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    timestamp = event.get("timestamp") or event.get("time") or "now"
                    event_type = event.get("type", "event")
                    print(f"   [{timestamp}] {event_type}: {json.dumps(event)}")
            except KeyboardInterrupt:
                print("\n👋 Exiting event stream.")

    if getattr(args, "events", False):
        _tail_events()
        if not getattr(args, "live", False):
            return

    if getattr(args, "live", False):
        try:
            from watchfiles import watch  # type: ignore
        except ImportError:
            print("⚠️  Install 'watchfiles' to use --live mode.")
            _render()
            return

        print("📡 Live dashboard — press Ctrl+C to exit.")
        _render(clear=True)
        try:
            for _ in watch("data/logs", "data/namespace_meta.json", debounce=1.0):
                _render(clear=True)
        except KeyboardInterrupt:
            print("\n👋 Exiting live dashboard.")
        return

    _render()


def _handle_system_clean(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    removed = system_clean(dry_run=args.dry_run, older_than_days=args.older_than, release=args.release)
    if args.dry_run:
        print("🧪 Dry run — files that would be removed:")
    else:
        print("🧹 Removed files:")
    if not removed:
        print("   • none")
        return
    for path in removed:
        print(f"   • {path}")


def _handle_shell(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    from yo import shell as yo_shell

    yo_shell.run_shell()


def _handle_system_snapshot(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    snapshot_path = system_snapshot(name=args.name, include_logs=not args.no_logs)
    print(f"📦 Snapshot created at {snapshot_path}")


def _handle_system_restore(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    archive_path = Path(args.archive)
    if not archive_path.exists():
        raise SystemExit(f"Snapshot archive not found: {archive_path}")
    restored = system_restore(archive_path, confirm=not args.yes)
    if not restored:
        print("ℹ️  Restore aborted.")
        return
    print("♻️  Restored files:")
    for path in restored:
        print(f"   • {path}")


def _handle_verify_signature(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    result = _verify_signature_artifacts()
    payload = {
        "success": result.get("success", False),
        "signer": result.get("signer"),
        "message": result.get("message"),
        "checksum": result.get("checksum"),
        "signature": result.get("signature"),
    }

    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return

    if payload["success"]:
        signer = payload["signer"] or "unknown signer"
        print(f"✅ Signature valid ({signer})")
    else:
        print("❌ Signature verification failed.")
        message = payload.get("message")
        if message:
            print(message)


def _handle_verify_clone(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    signature_result = _verify_signature_artifacts()
    clone_payload: dict[str, Any] = {
        "signature": signature_result,
        "checksum_matches_remote": None,
        "remote_error": None,
    }

    checksum_path = Path("data/logs/checksums/artifact_hashes.txt")
    remote_text = None
    if checksum_path.exists() and shutil.which("git"):
        fetch_proc = subprocess.run(
            ["git", "fetch", "origin", "main"],
            capture_output=True,
            text=True,
        )
        if fetch_proc.returncode != 0:
            clone_payload["remote_error"] = fetch_proc.stderr or fetch_proc.stdout
        else:
            show_proc = subprocess.run(
                ["git", "show", "origin/main:data/logs/checksums/artifact_hashes.txt"],
                capture_output=True,
                text=True,
            )
            if show_proc.returncode == 0:
                remote_text = show_proc.stdout
            else:
                clone_payload["remote_error"] = show_proc.stderr or show_proc.stdout

    if remote_text is not None and checksum_path.exists():
        local_text = checksum_path.read_text(encoding="utf-8")
        clone_payload["checksum_matches_remote"] = local_text.strip() == remote_text.strip()

    if getattr(args, "json", False):
        print(json.dumps(clone_payload, indent=2))
        return

    if signature_result.get("success"):
        signer = signature_result.get("signer") or "unknown signer"
        print(f"✅ Signature valid ({signer})")
    else:
        print("❌ Signature verification failed.")
        message = signature_result.get("message")
        if message:
            print(message)

    matches_remote = clone_payload["checksum_matches_remote"]
    if matches_remote is True:
        print("✅ Local checksum matches origin/main.")
    elif matches_remote is False:
        print("❌ Local checksum differs from origin/main.")
    else:
        print("ℹ️  Unable to compare checksum against origin/main.")
        if clone_payload.get("remote_error"):
            print(clone_payload["remote_error"])


def _handle_logs_tail(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    kind = getattr(args, "log_type", "events") or "events"
    if kind not in LOG_KINDS:
        raise SystemExit(f"Unknown log type '{kind}'. Choose from: {', '.join(sorted(LOG_KINDS))}.")

    log_path = _latest_log_path(kind)
    tail_lines: list[str] = []
    formatted_lines: list[str] = []
    if log_path:
        tail_lines = _read_log_tail(log_path, getattr(args, "lines", 20) or 20)
        formatted_lines = [_format_log_entry(kind, line) for line in tail_lines]

    if getattr(args, "json", False):
        payload = {
            "kind": kind,
            "log_path": str(log_path) if log_path else None,
            "lines": tail_lines,
        }
        print(json.dumps(payload, indent=2))
        return

    if not log_path or not tail_lines:
        print(f"ℹ️  No {kind} logs recorded yet.")
        return

    print(f"📄 Tail of {kind} log ({log_path}):")
    for line in formatted_lines:
        print(f"   • {line}")


def _handle_logs_collect(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    if not getattr(args, "chat_bug", False):
        raise SystemExit("Specify --chat-bug to collect chat diagnostics.")

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = Path(args.output or f"data/logs/chat_bug_{timestamp}.zip")
    dest.parent.mkdir(parents=True, exist_ok=True)

    log_map = {
        "web_startup.log": Path("data/logs/web_startup.log"),
        "ws_errors.log": Path("data/logs/ws_errors.log"),
        "web_deadlock.dump": Path("data/logs/web_deadlock.dump"),
    }
    metrics_path = Path("data/logs/metrics.jsonl")
    har_path = Path(args.har) if getattr(args, "har", None) else Path("data/logs/chat_bug.har")

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arcname, src in log_map.items():
            if src.exists():
                archive.write(src, arcname=arcname)
        if metrics_path.exists():
            archive.writestr("metrics_tail.txt", _tail_file(metrics_path, 50))
        if har_path.exists():
            archive.write(har_path, arcname=har_path.name)

    print(f"📦 Collected chat diagnostics -> {dest}")


def _handle_health_web(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8000)
    timeout = getattr(args, "timeout", 5)
    url = f"http://{host}:{port}/api/health"
    try:
        response = httpx.get(url, timeout=timeout)
    except Exception as exc:
        print(f"❌ Unable to reach {url}: {exc}")
        raise SystemExit(1) from exc

    if response.status_code != 200:
        print(f"❌ Web health check failed (HTTP {response.status_code}): {response.text}")
        raise SystemExit(1)

    payload = response.json()
    if payload.get("status") != "ok":
        print(f"❌ Web server not ready: {payload}")
        raise SystemExit(1)

    chat_url = f"http://{host}:{port}/chat"
    try:
        chat_response = httpx.get(chat_url, timeout=timeout, headers={"Accept": "text/html"})
    except Exception as exc:
        print(f"❌ Unable to fetch {chat_url}: {exc}")
        raise SystemExit(1) from exc

    if chat_response.status_code != 200:
        print(f"❌ /chat responded with HTTP {chat_response.status_code}")
        raise SystemExit(1)

    content_type = chat_response.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        print(f"❌ /chat returned unexpected content-type: {content_type}")
        raise SystemExit(1)

    elapsed_td = getattr(chat_response, "elapsed", None)
    elapsed_ms = None
    if elapsed_td is not None:
        elapsed_ms = elapsed_td.total_seconds() * 1000.0
        if elapsed_ms > 1000.0:
            print(f"❌ /chat responded in {elapsed_ms:.1f}ms (expected < 1000ms)")
            raise SystemExit(1)

    if elapsed_ms is not None:
        print(f"✅ Web server healthy at {url} (chat page {elapsed_ms:.1f}ms)")
    else:
        print(f"✅ Web server healthy at {url} (chat page ok)")


def _extract_reply_text(reply: Any) -> str:
    if reply is None:
        return ""
    if isinstance(reply, str):
        return reply.strip()
    if isinstance(reply, dict):
        text = reply.get("text")
        if isinstance(text, str):
            return text.strip()
        for key in ("response", "reply", "message", "content"):
            candidate = reply.get(key)
            if isinstance(candidate, str):
                return candidate.strip()
    try:
        return str(reply).strip()
    except Exception:
        return ""


def _extract_text_length(entry: Dict[str, Any]) -> int | None:
    reply = entry.get("reply")
    reply_text = _extract_reply_text(reply)
    if reply_text:
        return len(reply_text)
    token = entry.get("token")
    if isinstance(token, str):
        return len(token)
    text_len = entry.get("text_len")
    return text_len if isinstance(text_len, int) else None


def _handle_health_chat(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8000)
    timeout = getattr(args, "timeout", 8.0)
    message = getattr(args, "message", "probe")
    namespace = getattr(args, "ns", "default") or "default"
    force_fallback = bool(getattr(args, "force_fallback", False))

    url = f"http://{host}:{port}/api/chat"
    session_id = f"health-{int(time.time() * 1000)}"
    payload = {
        "namespace": namespace,
        "message": message,
        "session_id": session_id,
        "stream": True,
    }
    if force_fallback:
        payload["force_fallback"] = True

    try:
        response = httpx.post(url, json=payload, timeout=timeout)
    except Exception as exc:
        print(f"❌ Chat probe failed: {exc}")
        raise SystemExit(1) from exc

    if response.status_code != 200:
        print(f"❌ Chat probe returned HTTP {response.status_code}: {response.text}")
        raise SystemExit(1)

    data = response.json()
    reply_text = _extract_reply_text(data.get("reply"))
    if not reply_text:
        print(f"❌ Chat probe produced empty reply: {data}")
        raise SystemExit(1)

    if force_fallback and not data.get("fallback"):
        print(f"❌ Chat probe expected fallback reply but fallback flag was False: {data}")
        raise SystemExit(1)

    print(f"✅ Chat probe succeeded (fallback={data.get('fallback')})")


def _handle_health_ws(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8000)
    timeout = getattr(args, "timeout", 8.0)
    message = getattr(args, "message", "probe")
    namespace = getattr(args, "ns", "default") or "default"

    session_id = f"health-{int(time.time() * 1000)}"
    ws_url = f"ws://{host}:{port}/ws/chat/{session_id}"
    chat_url = f"http://{host}:{port}/api/chat"

    async def _probe() -> tuple[list[str], dict[str, Any]]:
        messages: list[str] = []
        async with websockets.connect(ws_url) as websocket:
            response = httpx.post(
                chat_url,
                json={
                    "namespace": namespace,
                    "message": message,
                    "session_id": session_id,
                    "stream": True,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    incoming = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                messages.append(incoming)
                if "\"chat_complete\"" in incoming:
                    break
            return messages, payload

    try:
        ws_messages, payload = asyncio.run(_probe())
    except Exception as exc:
        print(f"❌ WebSocket probe failed: {exc}")
        raise SystemExit(1) from exc

    reply_text = _extract_reply_text(payload.get("reply"))
    if any("\"chat_complete\"" in msg for msg in ws_messages) or reply_text:
        print(f"✅ WebSocket probe succeeded (fallback={payload.get('fallback')})")
        return

    print("❌ WebSocket probe did not receive completion frame.")
    raise SystemExit(1)


def _ensure_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise SystemExit(f"Port {port} on {host} is unavailable: {exc}") from exc


def _handle_web_run(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    host = getattr(args, "host", "127.0.0.1")
    port = int(getattr(args, "port", 8000))
    debug = bool(getattr(args, "debug", False))
    reload_enabled = bool(getattr(args, "reload", False))

    _ensure_port_available(host, port)

    os.environ["YO_WEB_HOST"] = host
    os.environ["YO_WEB_PORT"] = str(port)
    os.environ["YO_WEB_RELOAD"] = "1" if reload_enabled else "0"
    if debug:
        os.environ["YO_WEB_DEBUG"] = "1"
    else:
        os.environ.pop("YO_WEB_DEBUG", None)

    from yo import webui

    webui.configure_runtime(host, port, debug=debug)

    import uvicorn

    config = uvicorn.Config(
        "yo.webui:app",
        host=host,
        port=port,
        log_level="info",
        reload=reload_enabled,
        loop="asyncio",
        timeout_keep_alive=5,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        pass
def _format_metric_value(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def _handle_metrics_summarize(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    window = getattr(args, "since", None)
    try:
        summary = summarize_since(window)
    except ValueError as exc:
        raise SystemExit(f"Invalid --since value: {exc}") from exc

    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2))
        return

    print(f"📈 Metrics summary (window: {summary.get('window', 'all')})")
    print(f"Samples recorded: {summary.get('total', 0)}")
    print()
    for metric_type, info in summary.get("types", {}).items():
        print(f"[{metric_type}] {info.get('count', 0)} samples")
        fields = info.get("fields", {})
        if fields:
            for field, stats in fields.items():
                avg = _format_metric_value(stats.get("avg"))
                min_val = _format_metric_value(stats.get("min"))
                max_val = _format_metric_value(stats.get("max"))
                count = stats.get("count", 0)
                print(f"   • {field}: avg={avg} min={min_val} max={max_val} (n={count})")
        latest = info.get("latest") or {}
        if latest:
            timestamp = latest.get("timestamp", "unknown")
            print(f"     Latest sample: {timestamp}")
        print()


def _handle_analytics_report(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    window = getattr(args, "since", None)
    try:
        since_delta = parse_since_window(window) if window else None
    except ValueError as exc:
        raise SystemExit(f"Invalid --since value: {exc}") from exc

    entries = load_analytics(since=since_delta)
    summary = summarize_usage(entries)
    summary["window"] = window or "all"
    summary["enabled"] = analytics_enabled()

    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2))
        return

    if not analytics_enabled():
        print("⚠️  Analytics disabled (set YO_ANALYTICS=on to enable tracking).")
    print(f"🧭 Usage analytics (window: {summary['window']}, total samples: {summary.get('total', 0)})\n")

    commands = summary.get("commands") or []
    if commands:
        print("Commands:")
        for command, count in commands[:10]:
            print(f"   • {command}: {count}")
        print()
    namespaces = summary.get("namespaces") or []
    if namespaces:
        print("Namespaces touched:")
        for namespace, count in namespaces[:10]:
            print(f"   • {namespace}: {count}")
        print()

    chat_info = summary.get("chat") or {}
    if chat_info.get("total_sessions"):
        avg_latency = chat_info.get("avg_latency_seconds")
        avg_tokens = chat_info.get("avg_tokens")
        print("Chat sessions:")
        print(f"   • Total sessions: {chat_info['total_sessions']}")
        if avg_latency is not None:
            print(f"   • Avg latency: {avg_latency:.2f}s")
        if avg_tokens is not None:
            print(f"   • Avg tokens: {avg_tokens:.0f}")
        by_ns = chat_info.get("by_namespace") or []
        if by_ns:
            print(f"   • Sessions by namespace: {', '.join(f'{ns} ({count})' for ns, count in by_ns[:5])}")
        print()

    ingest_info = summary.get("ingest") or {}
    if ingest_info.get("total_runs"):
        avg_duration = ingest_info.get("avg_duration_seconds")
        print("Ingestion runs:")
        print(f"   • Total runs: {ingest_info['total_runs']}")
        if avg_duration is not None:
            print(f"   • Avg duration: {avg_duration:.2f}s")
        by_ns = ingest_info.get("by_namespace") or []
        if by_ns:
            print(f"   • Runs by namespace: {', '.join(f'{ns} ({count})' for ns, count in by_ns[:5])}")
        print()


def _handle_optimize_suggest(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    recommendations = generate_recommendations()
    if getattr(args, "json", False):
        print(json.dumps({"recommendations": recommendations}, indent=2))
        return
    if not recommendations:
        print("ℹ️  No optimisation recommendations at this time.")
        return

    print("🛠️  Optimisation suggestions:\n")
    for rec in recommendations:
        print(f"- {rec.get('title', rec.get('id', 'recommendation'))}")
        detail = rec.get("detail")
        if detail:
            print(f"    {detail}")
        if rec.get("action") != "env_update" and rec.get("next_steps"):
            next_steps = rec["next_steps"]
            if isinstance(next_steps, list):
                for step in next_steps:
                    print(f"    → {step}")
        print()


def _handle_optimize_apply(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    selections = generate_recommendations()
    ids = getattr(args, "ids", None)
    if ids:
        selections = [rec for rec in selections if rec.get("id") in ids]
    if not selections:
        print("ℹ️  No matching recommendations found.")
        return

    auto_recs = [rec for rec in selections if rec.get("action") == "env_update"]
    manual_recs = [rec for rec in selections if rec.get("action") != "env_update"]

    applied = apply_recommendations(auto_recs, auto_only=False)
    if applied:
        print("✅ Applied configuration updates:")
        for entry in applied:
            applied_env = entry.get("applied", {})
            for key, value in applied_env.items():
                print(f"   • {key}={value}")
    else:
        print("ℹ️  No automatic optimisations were applied.")

    if manual_recs:
        print("\nManual follow-ups required:")
        for rec in manual_recs:
            print(f" - {rec.get('title', rec.get('id', 'manual'))}")
            detail = rec.get("detail")
            if detail:
                print(f"     {detail}")
            steps = rec.get("next_steps") or []
            for step in steps:
                print(f"     → {step}")
def _handle_verify_ledger(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    ledger_path = Path("data/logs/verification_ledger.jsonl")
    if not ledger_path.exists():
        print("ℹ️  No verification ledger entries recorded yet.")
        return

    lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        print("ℹ️  Verification ledger is currently empty.")
        return

    entries: list[dict[str, Any]] = []
    for raw in reversed(lines[-10:]):
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError:
            continue

    if not entries:
        print("ℹ️  Verification ledger entries could not be parsed.")
        return

    print("🧾 Verification Ledger (most recent first)\n")
    for entry in entries:
        timestamp = entry.get("timestamp", "unknown")
        version = entry.get("version", "unknown")
        commit = entry.get("commit", "unknown")
        health = entry.get("health", "n/a")
        checksum_file = entry.get("checksum_file", "-")
        signature = entry.get("signature", "-")
        print(f"• {timestamp} — version {version} @ {commit}")
        print(f"   Health: {health}")
        print(f"   Checksum file: {checksum_file}")
        print(f"   Signature: {signature}")


def _handle_chat(args: argparse.Namespace, brain: YoBrain | None = None) -> None:
    if brain is None:
        brain = YoBrain()

    namespace = getattr(args, "ns", None) or getattr(brain, "active_namespace", _active_namespace_default())
    namespace = namespace or _active_namespace_default()

    history: list[dict[str, str]] = []

    def _send(message: str) -> None:
        if getattr(args, "stream", False):
            print(f"\n🧠 Yo ({namespace}):\n", end="")
            sys.stdout.flush()
            assembled = []
            citations: list[str] = []
            for chunk in brain.chat_stream(
                message=message,
                namespace=namespace,
                history=history,
                web=getattr(args, "web", False),
            ):
                if chunk.get("done"):
                    reply = chunk.get("response", "")
                    citations = chunk.get("citations") or []
                    history.append({"user": message, "assistant": reply})
                    if not reply.endswith("\n"):
                        print()
                    if citations:
                        print("🔗 Sources:")
                        for citation in citations[:5]:
                            print(f"   • {citation}")
                    break
                token = chunk.get("token", "")
                if token:
                    assembled.append(token)
                    print(token, end="", flush=True)
        else:
            payload = brain.chat(
                message=message,
                namespace=namespace,
                history=history,
                web=getattr(args, "web", False),
            )
            reply = payload.get("response", "")
            citations = payload.get("citations") or []
            history.append({"user": message, "assistant": reply})
            print(f"\n🧠 Yo ({namespace}):\n{reply}\n")
            if citations:
                print("🔗 Sources:")
                for citation in citations[:5]:
                    print(f"   • {citation}")

    if getattr(args, "message", None):
        message_text = " ".join(args.message).strip()
        if not message_text:
            raise SystemExit("Message cannot be empty.")
        _send(message_text)
        return

    print("🧠 Interactive chat mode. Type '/exit' to quit.\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"/exit", "/quit"}:
            break
        _send(user_input)


def _handle_package_release(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    manifest_path = Path(args.manifest) if getattr(args, "manifest", None) else Path("data/logs/integrity_manifest.json")
    release_dir = Path(args.output) if getattr(args, "output", None) else Path("releases")

    try:
        result = build_release_bundle(
            version=getattr(args, "version", None),
            signer=getattr(args, "signer", None),
            release_dir=release_dir,
            manifest_path=manifest_path,
        )
    except Exception as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc

    manifest = result.get("manifest_data", {})
    payload = {
        "bundle": result.get("bundle"),
        "signature": result.get("signature"),
        "manifest": result.get("manifest"),
        "version": manifest.get("version"),
        "commit": manifest.get("commit"),
        "health": manifest.get("health"),
    }

    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return

    print(f"📦 Release bundle created: {payload['bundle']}")
    print(f"🔐 Signature: {payload['signature']}")
    print(f"📝 Manifest: {payload['manifest']}")
    manifest_version_path = result.get("manifest_version")
    if manifest_version_path:
        print(f"🗂️  Version manifest: {manifest_version_path}")
    if payload.get("version"):
        print(f"Version: {payload['version']} @ {payload.get('commit', 'unknown')} (health {payload.get('health', 'n/a')})")


def _handle_release_list(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    releases = list_release_manifests()
    if getattr(args, "json", False):
        print(json.dumps(releases, indent=2))
        return

    if not releases:
        print("ℹ️  No release bundles packaged yet.")
        return

    print("📦 Packaged releases:\n")
    for entry in releases:
        timestamp = entry.get("timestamp", "unknown")
        version = entry.get("version", "unknown")
        health = entry.get("health", "n/a")
        bundle = entry.get("release_bundle", "-")
        print(f"• {version} — health {health} @ {timestamp}")
        print(f"   Bundle: {bundle}")


def _handle_release_info(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    manifest = load_release_manifest(args.version)
    if manifest is None:
        print(f"❌ Release manifest for {args.version} not found.")
        raise SystemExit(1)

    if getattr(args, "json", False):
        print(json.dumps(manifest, indent=2))
        return

    print(f"📦 Release {manifest.get('version', args.version)}")
    print(f"Commit: {manifest.get('commit', 'unknown')}")
    print(f"Health: {manifest.get('health', 'n/a')}")
    print(f"Packaged: {manifest.get('timestamp', 'unknown')}")
    print(f"Bundle: {manifest.get('release_bundle', '-')}")
    print(f"Signature: {manifest.get('bundle_signature', '-')}")
    print(f"Checksum: {manifest.get('bundle_checksum', '-')}")
    print(f"Manifest: {manifest.get('manifest_path', '-')}")


def _handle_verify_manifest(args: argparse.Namespace, __: YoBrain | None = None) -> None:
    manifest_path = Path(getattr(args, "path", None) or "data/logs/integrity_manifest.json")
    result = verify_integrity_manifest(manifest_path)

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return

    manifest = result.get("manifest") or {}
    version = manifest.get("version", "unknown")
    if result.get("success"):
        print(f"✅ Manifest valid for {version}")
        bundle = manifest.get("release_bundle")
        if bundle:
            print(f"Bundle: {bundle}")
    else:
        print("❌ Manifest verification failed.")
        for error in result.get("errors", []):
            print(f"- {error}")


def _handle_report_audit(args: argparse.Namespace, brain: YoBrain | None = None) -> None:
    if brain is None:
        brain = YoBrain()

    logs_dir = Path("data/logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    telemetry_summary = load_telemetry_summary() or build_telemetry_summary()
    test_summary = load_test_summary()
    test_history = load_test_history(limit=10)
    dependency_events = load_dependency_history(limit=10)

    namespace_stats = brain.namespace_activity()
    drift_window = _parse_since(DEFAULT_DRIFT_WINDOW)
    drift_stats = brain.namespace_drift(drift_window)

    lifecycle_events = load_lifecycle_history(limit=25)
    snapshots = list_snapshots(limit=5)

    checksums_dir = logs_dir / "checksums"
    signed_checksum_path = checksums_dir / "artifact_hashes.sig"
    checksum_file_path = checksums_dir / "artifact_hashes.txt"
    ledger_path = logs_dir / "verification_ledger.jsonl"

    audit_namespaces: list[dict[str, Any]] = []
    for name, stats in sorted(namespace_stats.items()):
        drift = drift_stats.get(name, {})
        documents = int(stats.get("documents", 0) or 0)
        chunks = int(stats.get("chunks", 0) or 0)
        growth_value = float(drift.get("growth_percent", stats.get("growth_percent", 0.0)) or 0.0)
        alerts: list[str] = []
        if documents > NAMESPACE_DOCUMENT_ALERT:
            alerts.append(f"Documents {documents} exceeds {NAMESPACE_DOCUMENT_ALERT}")
        if chunks > NAMESPACE_CHUNK_ALERT:
            alerts.append(f"Chunks {chunks} exceeds {NAMESPACE_CHUNK_ALERT}")
        if growth_value > NAMESPACE_GROWTH_ALERT:
            alerts.append(f"Growth {growth_value:.1f}% exceeds threshold")

        audit_namespaces.append(
            {
                "name": name,
                "last_ingested": stats.get("last_ingested"),
                "documents": documents,
                "documents_delta": stats.get("documents_delta"),
                "chunks": chunks,
                "chunks_delta": stats.get("chunks_delta"),
                "records": stats.get("records"),
                "growth_percent": growth_value,
                "ingest_runs": stats.get("ingest_runs"),
                "drift": drift,
                "alerts": alerts,
            }
        )

    checksum_file_str = str(checksum_file_path) if checksum_file_path.exists() else None
    signed_checksum_str = str(signed_checksum_path) if signed_checksum_path.exists() else None
    ledger_path_str = str(ledger_path) if ledger_path.exists() else None
    signature_check = _verify_signature_artifacts()

    audit_payload: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat(),
        "health": {
            "score": telemetry_summary.get("health_score"),
            "pass_rate": telemetry_summary.get("pass_rate_mean"),
            "latest_status": (test_summary or {}).get("status"),
            "timestamp": (test_summary or {}).get("timestamp"),
        },
        "namespaces": audit_namespaces,
        "dependency_events": dependency_events,
        "lifecycle": lifecycle_events,
        "snapshots": snapshots,
        "tests": {
            "latest": test_summary,
            "recent": test_history,
        },
        "drift_window": DEFAULT_DRIFT_WINDOW,
        "files": {
            "audit_json": str(logs_dir / "audit_report.json"),
            "audit_markdown": str(logs_dir / "audit_report.md"),
            "audit_html": str(logs_dir / "audit_report.html"),
        },
    }
    if checksum_file_str:
        audit_payload["checksum_file"] = checksum_file_str
    if signed_checksum_str:
        audit_payload["signed_checksum"] = signed_checksum_str
    if ledger_path_str:
        audit_payload["ledger_entry"] = ledger_path_str
    audit_payload["signature_valid"] = signature_check.get("success", False)
    audit_payload["verification_time"] = signature_check.get("timestamp")

    audit_json_path = logs_dir / "audit_report.json"
    audit_json_path.write_text(json.dumps(audit_payload, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append(f"# Yo Audit Report — {audit_payload['generated_at']}")
    health = audit_payload["health"]
    score_display = health.get("score")
    pass_rate = health.get("pass_rate")
    if isinstance(pass_rate, (int, float)) and pass_rate <= 1:
        pass_rate = pass_rate * 100
    lines.append("\n## Health")
    lines.append(f"- Score: {score_display if score_display is not None else 'n/a'}")
    lines.append(f"- Latest status: {health.get('latest_status') or 'unknown'}")
    lines.append(f"- Pass rate: {pass_rate:.1f}%" if isinstance(pass_rate, (int, float)) else "- Pass rate: n/a")

    lines.append("\n## Namespaces")
    if audit_namespaces:
        lines.append("| Namespace | Documents | Δ Docs | Chunks | Δ Chunks | Growth | Alerts |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |")
        for entry in audit_namespaces:
            alerts = "; ".join(entry["alerts"]) if entry["alerts"] else "—"
            growth = entry["growth_percent"]
            growth_display = f"{growth:.1f}%" if isinstance(growth, (int, float)) else "—"
            lines.append(
                f"| {entry['name']} | {entry['documents']} | {entry.get('documents_delta') or 0} | "
                f"{entry['chunks']} | {entry.get('chunks_delta') or 0} | {growth_display} | {alerts} |"
            )
    else:
        lines.append("No namespaces found.")

    if checksum_file_str or signed_checksum_str or ledger_path_str:
        lines.append("\n## Signed Verification")
        lines.append(f"- Checksum file: {checksum_file_str or 'n/a'}")
        lines.append(f"- Signature: {signed_checksum_str or 'n/a'}")
        lines.append(f"- Ledger: {ledger_path_str or 'n/a'}")

    lines.append("\n## Dependencies")
    if dependency_events:
        for event in dependency_events:
            packages = ", ".join(event.get("packages", []))
            lines.append(f"- {event.get('timestamp')}: {event.get('action')} ({packages})")
    else:
        lines.append("- No dependency events recorded.")

    lines.append("\n## Lifecycle")
    if lifecycle_events:
        for event in lifecycle_events:
            detail = event.get("detail", {})
            lines.append(f"- {event.get('timestamp')}: {event.get('action')} — {detail}")
    else:
        lines.append("- No lifecycle events logged.")

    lines.append("\n## Snapshots")
    if snapshots:
        for snap in snapshots:
            lines.append(
                f"- {snap.get('created_at')}: {snap.get('name')} (files={len(snap.get('files', []))})"
            )
    else:
        lines.append("- No snapshots found.")

    audit_md_path = logs_dir / "audit_report.md"
    md_content = "\n".join(lines) + "\n"
    audit_md_path.write_text(md_content, encoding="utf-8")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Yo Audit Report</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 2rem; line-height: 1.6; max-width: 960px; margin: auto; }}
      pre {{ background: #1f2933; color: #f5f7fa; padding: 1rem; border-radius: 8px; overflow-x: auto; }}
      h1, h2 {{ color: #1f2933; }}
    </style>
  </head>
  <body>
    <h1>Yo Audit Report</h1>
    <pre>{html.escape(md_content)}</pre>
  </body>
</html>
"""
    audit_html_path = logs_dir / "audit_report.html"
    audit_html_path.write_text(html_content, encoding="utf-8")

    if getattr(args, "json", False):
        print(json.dumps(audit_payload, indent=2))
        return

    if getattr(args, "md", False):
        print(md_content)

    if getattr(args, "html", False):
        print(audit_html_path.read_text(encoding="utf-8"))

    _rich_print("🧾 Audit report generated:", style="green")
    _rich_print(f" - JSON: {audit_json_path}")
    _rich_print(f" - Markdown: {audit_md_path}")
    _rich_print(f" - HTML: {audit_html_path}")
    if checksum_file_str:
        _rich_print(f" - Checksum: {checksum_file_str}")
    if signed_checksum_str:
        _rich_print(f" - Signature: {signed_checksum_str}")
    if ledger_path_str:
        _rich_print(f" - Ledger: {ledger_path_str}")

    if console and Table and audit_namespaces:
        table = Table(title="Namespace Snapshot")
        table.add_column("Namespace", style="cyan")
        table.add_column("Documents", justify="right")
        table.add_column("Growth", justify="right")
        table.add_column("Alerts", justify="left")
        for entry in audit_namespaces:
            growth = entry["growth_percent"]
            growth_display = f"{growth:.1f}%" if isinstance(growth, (int, float)) else "—"
            alerts = ", ".join(entry["alerts"]) if entry["alerts"] else "—"
            table.add_row(
                entry["name"],
                f"{entry['documents']:,}",
                growth_display,
                alerts,
            )
        console.print(table)

    if checksum_file_str or signed_checksum_str or ledger_path_str:
        print("\nSigned verification artifacts:")
        if checksum_file_str:
            print(f"   • Checksum: {checksum_file_str}")
        if signed_checksum_str:
            print(f"   • Signature: {signed_checksum_str}")
        if ledger_path_str:
            print(f"   • Ledger: {ledger_path_str}")

def _add_ns_options(parser: argparse.ArgumentParser) -> None:
    default_ns = _active_namespace_default()
    parser.add_argument(
        "--ns",
        default=default_ns,
        help=f"Namespace to target (default: {default_ns})",
    )


def build_parser() -> argparse.ArgumentParser:
    global MAIN_PARSER
    COMMAND_REGISTRY.clear()

    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    MAIN_PARSER = parser
    subparsers = parser.add_subparsers(dest="command", required=True)

    def _add_top_level(
        name: str,
        *,
        help_text: str,
        category: Optional[str] = None,
        aliases: Optional[Sequence[str]] = None,
    ) -> argparse.ArgumentParser:
        kwargs: Dict[str, Any] = {
            "help": help_text,
            "description": help_text,
        }
        if aliases:
            parser_obj = subparsers.add_parser(name, aliases=list(aliases), **kwargs)
        else:
            parser_obj = subparsers.add_parser(name, **kwargs)
        _register_command(name, parser_obj, help_text=help_text, category=category, aliases=aliases)
        return parser_obj

    add_parser = _add_top_level("add", help_text="Ingest files into a namespace", category="Ingestion")
    add_parser.add_argument("path", help="Path to a file or directory to ingest")
    _add_ns_options(add_parser)
    add_parser.set_defaults(handler=_handle_add)

    ask_parser = _add_top_level("ask", help_text="Ask a question against a namespace", category="Retrieval")
    ask_parser.add_argument("question", help="Question to ask")
    _add_ns_options(ask_parser)
    ask_parser.add_argument("--web", action="store_true", help="Blend cached web context into answers")
    ask_parser.add_argument(
        "--debug",
        action="store_true",
        help="Print chat timing diagnostics instead of synthesized answer",
    )
    ask_parser.add_argument(
        "--timeout",
        type=float,
        help="Override chat timeout (seconds) when --debug is used",
    )
    ask_parser.set_defaults(handler=_handle_ask)

    chat_parser = _add_top_level("chat", help_text="Chat with YoBrain", category="Retrieval")
    chat_parser.add_argument("message", nargs="*", help="Message to send immediately")
    chat_parser.add_argument("--ns", help="Namespace to target (default: active namespace)")
    chat_parser.add_argument("--web", action="store_true", help="Blend cached web context into replies")
    chat_parser.add_argument("--stream", action="store_true", help="Stream tokens as they generate")
    chat_parser.set_defaults(handler=_handle_chat)

    summarize_parser = _add_top_level("summarize", help_text="Summarize a namespace", category="Retrieval")
    _add_ns_options(summarize_parser)
    summarize_parser.set_defaults(handler=_handle_summarize)

    namespace_parser = _add_top_level(
        "namespace",
        help_text="Namespace management",
        category="Namespace",
        aliases=["ns"],
    )
    ns_sub = namespace_parser.add_subparsers(dest="namespace_command", required=True)

    ns_list_parser = ns_sub.add_parser("list", help="List namespaces", description="List namespaces")
    ns_list_parser.set_defaults(handler=_handle_ns_list)

    ns_switch_parser = ns_sub.add_parser("switch", help="Switch the active namespace", description="Switch active namespace")
    ns_switch_parser.add_argument("name", nargs="?", help="Namespace to activate")
    ns_switch_parser.add_argument("--ns", dest="name", help=argparse.SUPPRESS)
    ns_switch_parser.set_defaults(handler=_handle_ns_switch)

    ns_purge_parser = ns_sub.add_parser("purge", help="Delete a namespace and its data", description="Delete namespace")
    ns_purge_parser.add_argument("name", nargs="?", help="Namespace to purge")
    _add_ns_options(ns_purge_parser)
    ns_purge_parser.set_defaults(handler=_handle_ns_purge)

    ns_delete_parser = ns_sub.add_parser("delete", help=argparse.SUPPRESS, description="Delete namespace")
    ns_delete_parser.add_argument("name", nargs="?", help=argparse.SUPPRESS)
    _add_ns_options(ns_delete_parser)
    ns_delete_parser.set_defaults(handler=_handle_ns_purge)

    ns_stats_parser = ns_sub.add_parser("stats", help="Show namespace statistics", description="Namespace statistics overview")
    ns_stats_parser.set_defaults(handler=_handle_ns_stats)

    ns_drift_parser = ns_sub.add_parser("drift", help="Show namespace growth over a window", description="Namespace growth analytics")
    ns_drift_parser.add_argument("--since", default=DEFAULT_DRIFT_WINDOW, help="Time window (e.g., 24h, 7d, 2w)")
    ns_drift_parser.set_defaults(handler=_handle_ns_drift)

    config_parser = _add_top_level("config", help_text="Configuration management", category="Configuration")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)

    config_view = config_sub.add_parser("view", help="Display the merged configuration", description="Display configuration")
    config_view.add_argument("--ns", help="Namespace to focus on")
    config_view.set_defaults(handler=_handle_config_view)

    config_set = config_sub.add_parser("set", help="Set a configuration value", description="Set configuration value")
    config_set.add_argument("key", choices=CONFIG_MUTABLE_KEYS, help="Configuration key to update")
    config_set.add_argument("value", help="Value to assign")
    config_set.add_argument("--ns", help="Namespace override (optional)")
    config_set.set_defaults(handler=_handle_config_set)

    config_reset = config_sub.add_parser("reset", help="Reset configuration values", description="Reset configuration")
    config_reset.add_argument("key", nargs="?", choices=CONFIG_MUTABLE_KEYS, help="Specific key to reset")
    config_reset.add_argument("--ns", help="Namespace override (optional)")
    config_reset.set_defaults(handler=_handle_config_reset)

    config_edit = config_sub.add_parser("edit", help="Open configuration in $EDITOR", description="Edit configuration via your editor")
    config_edit.set_defaults(handler=_handle_config_edit)

    deps_parser = _add_top_level("deps", help_text="Dependency intelligence tools", category="Dependencies")
    deps_sub = deps_parser.add_subparsers(dest="deps_command", required=True)

    deps_check = deps_sub.add_parser("check", help="Inspect dependency status", description="Inspect dependency status")
    deps_check.set_defaults(handler=_handle_deps_check)

    deps_repair = deps_sub.add_parser("repair", help="Attempt to resolve missing dependencies", description="Repair missing dependencies")
    deps_repair.set_defaults(handler=_handle_deps_repair)

    deps_freeze = deps_sub.add_parser("freeze", help="Write requirements lockfile", description="Freeze dependencies")
    deps_freeze.set_defaults(handler=_handle_deps_freeze)

    deps_diff = deps_sub.add_parser("diff", help="Compare requirements.txt with the lockfile", description="Compare requirements with lockfile")
    deps_diff.set_defaults(handler=_handle_deps_diff)

    deps_sync = deps_sub.add_parser("sync", help="Install dependencies from the lockfile", description="Sync dependencies from lockfile")
    deps_sync.set_defaults(handler=_handle_deps_sync)

    telemetry_parser = _add_top_level("telemetry", help_text="Test telemetry utilities", category="Telemetry")
    telemetry_sub = telemetry_parser.add_subparsers(dest="telemetry_command", required=True)

    telemetry_report = telemetry_sub.add_parser("report", help="Show recent test telemetry", description="Show telemetry report")
    telemetry_report.set_defaults(handler=_handle_telemetry_report)

    telemetry_analyze = telemetry_sub.add_parser("analyze", help="Analyze test telemetry trends", description="Analyze telemetry trends")
    telemetry_analyze.add_argument("--json", action="store_true", help="Output raw JSON payload")
    telemetry_analyze.add_argument("--release", action="store_true", help="Show release metadata (version/commit/health)")
    telemetry_analyze.set_defaults(handler=_handle_telemetry_analyze)
    telemetry_trace = telemetry_sub.add_parser(
        "trace",
        help="Trace chat delivery for a session",
        description="Inspect chat timing and WebSocket events for a session id",
    )
    telemetry_trace.add_argument("--session", required=True, help="Session id to inspect")
    telemetry_trace.set_defaults(handler=_handle_telemetry_trace)

    telemetry_archive = telemetry_sub.add_parser("archive", help="Archive the latest telemetry summary", description="Archive telemetry summary")
    telemetry_archive.set_defaults(handler=_handle_telemetry_archive)

    telemetry_archives = telemetry_sub.add_parser("archives", help="List telemetry archive files", description="List telemetry archives")
    telemetry_archives.add_argument("--limit", type=int, help="Number of recent archives to show")
    telemetry_archives.set_defaults(handler=_handle_telemetry_archives_list)

    logs_parser = _add_top_level("logs", help_text="Inspect session and event logs", category="Insights")
    logs_sub = logs_parser.add_subparsers(dest="logs_command", required=True)
    logs_tail = logs_sub.add_parser("tail", help="Tail the latest log file", description="Tail session logs")
    logs_tail.add_argument(
        "--type",
        dest="log_type",
        choices=sorted(LOG_KINDS),
        default="events",
        help="Log type to inspect (default: events)",
    )
    logs_tail.add_argument(
        "--lines",
        type=int,
        default=20,
        help="Number of lines to display (default: 20)",
    )
    logs_tail.add_argument("--json", action="store_true", help="Output raw JSON payload")
    logs_tail.set_defaults(handler=_handle_logs_tail)

    logs_collect = logs_sub.add_parser("collect", help="Collect diagnostic logs", description="Collect log bundles")
    logs_collect.add_argument("--chat-bug", action="store_true", help="Bundle chat-related diagnostics")
    logs_collect.add_argument("--har", help="Path to a HAR file captured from the browser")
    logs_collect.add_argument("--output", help="Destination zip path")
    logs_collect.set_defaults(handler=_handle_logs_collect)

    metrics_parser = _add_top_level("metrics", help_text="Summarise recorded metrics", category="Insights")
    metrics_sub = metrics_parser.add_subparsers(dest="metrics_command", required=True)
    metrics_summary = metrics_sub.add_parser("summarize", help="Summarize collected metrics", description="Summarize metrics window")
    metrics_summary.add_argument("--since", help="Time window (e.g., 24h, 7d)")
    metrics_summary.add_argument("--json", action="store_true", help="Output summary as JSON")
    metrics_summary.set_defaults(handler=_handle_metrics_summarize)

    analytics_parser = _add_top_level("analytics", help_text="Usage analytics overview", category="Insights")
    analytics_sub = analytics_parser.add_subparsers(dest="analytics_command", required=True)
    analytics_report = analytics_sub.add_parser("report", help="Summarize usage analytics", description="Summarize usage analytics")
    analytics_report.add_argument("--since", help="Time window (e.g., 30d)")
    analytics_report.add_argument("--json", action="store_true", help="Output analytics as JSON")
    analytics_report.set_defaults(handler=_handle_analytics_report)

    optimize_parser = _add_top_level("optimize", help_text="Self-optimization helpers", category="Insights")
    optimize_sub = optimize_parser.add_subparsers(dest="optimize_command", required=True)
    optimize_suggest = optimize_sub.add_parser("suggest", help="List current optimisation recommendations", description="List optimisation suggestions")
    optimize_suggest.add_argument("--json", action="store_true", help="Output recommendations as JSON")
    optimize_suggest.set_defaults(handler=_handle_optimize_suggest)
    optimize_apply = optimize_sub.add_parser("apply", help="Apply automatic recommendations", description="Apply optimisation recommendations")
    optimize_apply.add_argument("--id", dest="ids", action="append", help="Recommendation id to apply (may repeat)")
    optimize_apply.add_argument("--include-manual", action="store_true", help="Include manual recommendations in output")
    optimize_apply.set_defaults(handler=_handle_optimize_apply)

    web_parser = _add_top_level("web", help_text="Launch the Yo web server", category="Utilities")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    web_parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    web_parser.add_argument("--debug", action="store_true", help="Enable debug instrumentation and faulthandler")
    web_parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development only)")
    web_parser.set_defaults(handler=_handle_web_run)

    health_parser = _add_top_level("health", help_text="Overall system health insights", category="Insights")
    health_parser.add_argument("action", nargs="?", default="report", help=argparse.SUPPRESS)
    health_parser.add_argument("--json", action="store_true", help="Output report as JSON")
    health_parser.add_argument("--host", default="127.0.0.1", help="Target host for web health checks")
    health_parser.add_argument("--port", type=int, default=8000, help="Target port for web health checks")
    health_parser.add_argument("--timeout", type=float, default=5.0, help="Timeout for web health probe (seconds)")
    health_parser.add_argument("--message", default="probe", help="Probe message for chat/WebSocket health")
    health_parser.add_argument("--ns", default="default", help="Namespace for chat/WebSocket probes")
    health_parser.add_argument(
        "--force-fallback",
        action="store_true",
        help="Force REST fallback path when probing chat health",
    )
    health_parser.set_defaults(handler=_handle_health_report)

    system_parser = _add_top_level("system", help_text="Lifecycle and maintenance tools", category="Maintenance")
    system_sub = system_parser.add_subparsers(dest="system_command", required=True)

    system_clean_parser = system_sub.add_parser("clean", help="Remove stale logs and artifacts", description="Remove stale logs")
    system_clean_parser.add_argument("--dry-run", action="store_true", help="Show files without deleting them")
    system_clean_parser.add_argument(
        "--older-than",
        type=int,
        default=14,
        help="Remove logs older than this many days (default: 14)",
    )
    system_clean_parser.add_argument(
        "--release",
        action="store_true",
        help="Also remove packaged releases and integrity manifests",
    )
    system_clean_parser.set_defaults(handler=_handle_system_clean)

    system_snapshot_parser = system_sub.add_parser("snapshot", help="Create a configuration snapshot archive", description="Create snapshot")
    system_snapshot_parser.add_argument("--name", help="Optional snapshot name")
    system_snapshot_parser.add_argument("--no-logs", action="store_true", help="Exclude log files from the snapshot")
    system_snapshot_parser.set_defaults(handler=_handle_system_snapshot)

    system_restore_parser = system_sub.add_parser("restore", help="Restore telemetry/config from a snapshot archive", description="Restore snapshot")
    system_restore_parser.add_argument("archive", help="Path to the snapshot archive (.tar.gz)")
    system_restore_parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    system_restore_parser.set_defaults(handler=_handle_system_restore)

    report_parser = _add_top_level("report", help_text="Generate diagnostic reports", category="Insights")
    report_sub = report_parser.add_subparsers(dest="report_command", required=True)

    report_audit = report_sub.add_parser("audit", help="Generate system audit report", description="Produce JSON, Markdown, and HTML audit summaries")
    report_audit.add_argument("--json", action="store_true", help="Print raw JSON to stdout")
    report_audit.add_argument("--md", action="store_true", help="Print Markdown summary to stdout")
    report_audit.add_argument("--html", action="store_true", help="Print HTML summary to stdout")
    report_audit.set_defaults(handler=_handle_report_audit)

    explain_parser = _add_top_level("explain", help_text="Explain recent operations", category="Telemetry")
    explain_sub = explain_parser.add_subparsers(dest="explain_command", required=True)

    explain_verify = explain_sub.add_parser("verify", help="Explain the latest verification run", description="Explain verify results")
    explain_verify.add_argument("--web", action="store_true", help="Fetch external context for missing packages")
    explain_verify.add_argument("--json", action="store_true", help="Output explanation as JSON")
    explain_verify.add_argument("--compact", action="store_true", help="Show condensed summary")
    explain_verify.set_defaults(handler=_handle_explain_verify)

    dashboard_parser = _add_top_level("dashboard", help_text="Show the developer dashboard", category="Insights")
    dashboard_parser.add_argument("--live", action="store_true", help="Stream dashboard updates in real time")
    dashboard_parser.add_argument("--events", action="store_true", help="Tail live event telemetry")
    dashboard_parser.set_defaults(handler=_handle_dashboard_cli)

    cache_parser = _add_top_level("cache", help_text="Web cache utilities", category="Utilities")
    cache_sub = cache_parser.add_subparsers(dest="cache_command", required=True)

    cache_list_parser = cache_sub.add_parser("list", help="List cached web results", description="List cached web results")
    cache_list_parser.set_defaults(handler=_handle_cache_list)

    cache_clear_parser = cache_sub.add_parser("clear", help="Clear cached web results", description="Clear cached results")
    cache_clear_parser.set_defaults(handler=_handle_cache_clear)

    compact_parser = _add_top_level("compact", help_text="Vacuum the Milvus Lite store", category="Maintenance")
    compact_parser.set_defaults(handler=_handle_compact)

    shell_parser = _add_top_level("shell", help_text="Open the Yo developer shell", category="Utilities")
    shell_parser.set_defaults(handler=_handle_shell)

    package_parser = _add_top_level("package", help_text="Release packaging utilities", category="Release")
    package_sub = package_parser.add_subparsers(dest="package_command", required=True)
    package_release_parser = package_sub.add_parser(
        "release",
        help="Create a signed release bundle",
        description="Create a signed release bundle with checksums and manifest",
    )
    package_release_parser.add_argument("--version", help="Override detected version tag")
    package_release_parser.add_argument("--signer", help="GPG key identity to use for signing")
    package_release_parser.add_argument("--output", help="Directory to store the release bundle (default: releases/)")
    package_release_parser.add_argument(
        "--manifest",
        help="Path for the integrity manifest (default: data/logs/integrity_manifest.json)",
    )
    package_release_parser.add_argument("--json", action="store_true", help="Output result as JSON")
    package_release_parser.set_defaults(handler=_handle_package_release)

    release_parser = _add_top_level("release", help_text="Inspect packaged releases", category="Release")
    release_sub = release_parser.add_subparsers(dest="release_command", required=True)

    release_list_parser = release_sub.add_parser("list", help="List packaged releases", description="List packaged releases")
    release_list_parser.add_argument("--json", action="store_true", help="Output releases as JSON")
    release_list_parser.set_defaults(handler=_handle_release_list)

    release_info_parser = release_sub.add_parser("info", help="Show manifest details for a release", description="Show release manifest details")
    release_info_parser.add_argument("version", help="Release version to inspect (e.g., v0.5.0)")
    release_info_parser.add_argument("--json", action="store_true", help="Output manifest as JSON")
    release_info_parser.set_defaults(handler=_handle_release_info)

    verify_parser = _add_top_level("verify", help_text="Run the regression test suite", category="Validation")
    verify_parser.set_defaults(handler=run_test, verify_command=None)
    verify_sub = verify_parser.add_subparsers(dest="verify_command")
    verify_sub.required = False

    verify_ledger = verify_sub.add_parser("ledger", help="Show recent verification ledger entries", description="Display verification ledger entries")
    verify_ledger.set_defaults(handler=_handle_verify_ledger)

    verify_signature_parser = verify_sub.add_parser("signature", help="Validate checksum signature", description="Verify checksum signature authenticity")
    verify_signature_parser.add_argument("--json", action="store_true", help="Output result as JSON")
    verify_signature_parser.set_defaults(handler=_handle_verify_signature)

    verify_clone_parser = verify_sub.add_parser("clone", help="Validate signature and remote checksum against origin/main", description="Verify signature and compare checksums with origin")
    verify_clone_parser.add_argument("--json", action="store_true", help="Output result as JSON")
    verify_clone_parser.set_defaults(handler=_handle_verify_clone)

    verify_manifest_parser = verify_sub.add_parser(
        "manifest",
        help="Validate integrity manifest and release bundle",
        description="Validate integrity manifest and release bundle",
    )
    verify_manifest_parser.add_argument("--path", help="Path to integrity_manifest.json")
    verify_manifest_parser.add_argument("--json", action="store_true", help="Output result as JSON")
    verify_manifest_parser.set_defaults(handler=_handle_verify_manifest)

    doctor_parser = _add_top_level("doctor", help_text="Diagnose common local setup issues", category="Validation")
    doctor_parser.set_defaults(handler=run_doctor)

    help_parser = _add_top_level("help", help_text="Show command help", category="Utilities")
    help_parser.add_argument("topic", nargs="?", help="Command to describe")
    help_parser.set_defaults(handler=_handle_help)

    return parser


def main() -> None:
    parser = build_parser()
    argv = _expand_aliases(sys.argv)
    args = parser.parse_args(argv[1:])

    handler: Optional[Handler] = getattr(args, "handler", None)
    if handler is None:
        parser.error("No command provided")

    brain: YoBrain | None = None
    if args.command not in {
        "verify",
        "doctor",
        "config",
        "telemetry",
        "deps",
        "explain",
        "dashboard",
        "health",
        "system",
        "package",
        "release",
        "web",
        "help",
    }:
        ns_override = getattr(args, "ns", None)
        brain = YoBrain(namespace=ns_override)

    command_name = getattr(args, "command", "unknown")
    start_time = time.perf_counter()
    success = True
    try:
        handler(args, brain)
    except ValueError as exc:
        success = False
        print(f"❌ {exc}")
        raise SystemExit(1) from exc
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        if code not in (0, None):
            success = False
        raise
    finally:
        duration = time.perf_counter() - start_time
        try:
            namespace = getattr(args, "ns", None)
            if not namespace and brain and getattr(brain, "active_namespace", None):
                namespace = brain.active_namespace
            flags: Dict[str, Any] = {}
            for field in ("stream", "web", "json", "release", "action", "since"):
                if hasattr(args, field):
                    value = getattr(args, field)
                    if isinstance(value, (str, int, bool)):
                        flags[field] = value
            record_cli_command(
                command_name,
                duration_seconds=duration,
                namespace=namespace,
                success=success,
                flags=flags or None,
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
