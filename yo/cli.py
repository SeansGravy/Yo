"""Command line entry point for Yo."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from importlib import metadata as importlib_metadata
from importlib import util as import_util
from pathlib import Path
from typing import Callable, Literal, Optional, Sequence

Status = Literal["ok", "warn", "fail"]

from packaging.version import InvalidVersion, Version

from yo.backends import detect_backends
from yo.brain import IngestionError, MissingDependencyError, YoBrain
from yo.config import get_config, reset_config, serialize_config, update_config_value
from yo.verify import write_test_summary


Handler = Callable[[argparse.Namespace, YoBrain | None], None]

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
        raise ValueError("Namespace name is required.")
    return str(name)


def run_test(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    """Execute the regression test script if available."""

    script = Path.cwd() / "yo_full_test.sh"
    if not script.exists():
        print("⚠️  yo_full_test.sh not found. Please recreate it first.")
        raise SystemExit(1)

    backends = detect_backends()

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
        write_test_summary("✅ Verify successful", logfile=str(logfile))
        return

    print(
        f"\n❌ Verification failed with exit code {result.returncode}. "
        f"Review {logfile.name} for details.\n"
    )
    write_test_summary(
        f"❌ Verify failed (exit {result.returncode})",
        logfile=str(logfile),
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
    brain.ask(args.question, namespace=args.ns, web=args.web)


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


def _add_ns_options(parser: argparse.ArgumentParser) -> None:
    default_ns = _active_namespace_default()
    parser.add_argument(
        "--ns",
        default=default_ns,
        help=f"Namespace to target (default: {default_ns})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Ingest files into a namespace")
    add_parser.add_argument("path", help="Path to a file or directory to ingest")
    _add_ns_options(add_parser)
    add_parser.set_defaults(handler=_handle_add)

    ask_parser = subparsers.add_parser("ask", help="Ask a question against a namespace")
    ask_parser.add_argument("question", help="Question to ask")
    _add_ns_options(ask_parser)
    ask_parser.add_argument("--web", action="store_true", help="Blend cached web context into answers")
    ask_parser.set_defaults(handler=_handle_ask)

    summarize_parser = subparsers.add_parser("summarize", help="Summarize a namespace")
    _add_ns_options(summarize_parser)
    summarize_parser.set_defaults(handler=_handle_summarize)

    namespace_parser = subparsers.add_parser(
        "namespace",
        help="Namespace management",
        aliases=["ns"],
    )
    ns_sub = namespace_parser.add_subparsers(dest="namespace_command", required=True)

    ns_list_parser = ns_sub.add_parser("list", help="List namespaces")
    ns_list_parser.set_defaults(handler=_handle_ns_list)

    ns_switch_parser = ns_sub.add_parser("switch", help="Switch the active namespace")
    ns_switch_parser.add_argument("name", nargs="?", help="Namespace to activate")
    ns_switch_parser.add_argument("--ns", dest="name", help=argparse.SUPPRESS)
    ns_switch_parser.set_defaults(handler=_handle_ns_switch)

    ns_purge_parser = ns_sub.add_parser("purge", help="Delete a namespace and its data")
    ns_purge_parser.add_argument("name", nargs="?", help="Namespace to purge")
    ns_purge_parser.add_argument("--ns", dest="name", help=argparse.SUPPRESS)
    ns_purge_parser.set_defaults(handler=_handle_ns_purge)

    ns_delete_parser = ns_sub.add_parser("delete", help=argparse.SUPPRESS)
    ns_delete_parser.add_argument("name", nargs="?", help=argparse.SUPPRESS)
    ns_delete_parser.add_argument("--ns", dest="name", help=argparse.SUPPRESS)
    ns_delete_parser.set_defaults(handler=_handle_ns_purge)

    config_parser = subparsers.add_parser("config", help="Configuration management")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)

    config_view = config_sub.add_parser("view", help="Display the merged configuration")
    config_view.add_argument("--ns", help="Namespace to focus on")
    config_view.set_defaults(handler=_handle_config_view)

    config_set = config_sub.add_parser("set", help="Set a configuration value")
    config_set.add_argument("key", choices=CONFIG_MUTABLE_KEYS, help="Configuration key to update")
    config_set.add_argument("value", help="Value to assign")
    config_set.add_argument("--ns", help="Namespace override (optional)")
    config_set.set_defaults(handler=_handle_config_set)

    config_reset = config_sub.add_parser("reset", help="Reset configuration values")
    config_reset.add_argument("key", nargs="?", choices=CONFIG_MUTABLE_KEYS, help="Specific key to reset")
    config_reset.add_argument("--ns", help="Namespace override (optional)")
    config_reset.set_defaults(handler=_handle_config_reset)

    cache_parser = subparsers.add_parser("cache", help="Web cache utilities")
    cache_sub = cache_parser.add_subparsers(dest="cache_command", required=True)

    cache_list_parser = cache_sub.add_parser("list", help="List cached web results")
    cache_list_parser.set_defaults(handler=_handle_cache_list)

    cache_clear_parser = cache_sub.add_parser("clear", help="Clear cached web results")
    cache_clear_parser.set_defaults(handler=_handle_cache_clear)

    compact_parser = subparsers.add_parser("compact", help="Vacuum the Milvus Lite store")
    compact_parser.set_defaults(handler=_handle_compact)

    verify_parser = subparsers.add_parser("verify", help="Run the regression test suite")
    verify_parser.set_defaults(handler=run_test)

    doctor_parser = subparsers.add_parser("doctor", help="Diagnose common local setup issues")
    doctor_parser.set_defaults(handler=run_doctor)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    handler: Optional[Handler] = getattr(args, "handler", None)
    if handler is None:
        parser.error("No command provided")

    brain: YoBrain | None = None
    if args.command not in {"verify", "doctor", "config"}:
        ns_override = getattr(args, "ns", None)
        brain = YoBrain(namespace=ns_override)

    try:
        handler(args, brain)
    except ValueError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
