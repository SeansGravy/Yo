"""Command line entry point for Yo."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from importlib import metadata, util as import_util
from pathlib import Path
from typing import Callable, Optional

from packaging.version import Version

from yo.brain import YoBrain


Handler = Callable[[argparse.Namespace, YoBrain | None], None]


def run_test(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    """Execute the regression test script if available."""

    script = Path.cwd() / "yo_full_test.sh"
    if not script.exists():
        print("⚠️  yo_full_test.sh not found. Please recreate it first.")
        raise SystemExit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logfile = Path.cwd() / f"yo_test_results_{ts}.log"
    print(f"🧠 Running full Yo test suite… (logging to {logfile.name})")

    env = dict(os.environ)
    env["YO_LOGFILE"] = str(logfile)

    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        env=env,
    )

    if result.returncode == 0:
        print(f"\n✅ Verification complete. Check {logfile.name} for full details.\n")
        return

    print(
        f"\n❌ Verification failed with exit code {result.returncode}. "
        f"Review {logfile.name} for details.\n"
    )
    raise SystemExit(result.returncode)


def run_doctor(_: argparse.Namespace, __: YoBrain | None = None) -> None:
    """Run a quick environment diagnostic to help with local setup issues."""

    import platform
    import shutil

    def _report(title: str, ok: bool, detail: str = "") -> bool:
        icon = "✅" if ok else "❌"
        print(f"{icon} {title}")
        if detail:
            for line in detail.strip().splitlines():
                print(f"   {line}")
        return ok

    def _run_check(title: str, check: Callable[[], tuple[bool, str]]) -> bool:
        try:
            ok, detail = check()
        except Exception as exc:  # pragma: no cover - defensive guard
            ok, detail = False, str(exc)
        return _report(title, ok, detail)

    print("🩺 Yo Doctor — checking your setup\n")

    all_ok = True

    def _check_python() -> tuple[bool, str]:
        version = platform.python_version()
        ok = sys.version_info >= (3, 9)
        detail = f"Detected Python {version}." + ("" if ok else " Please use Python 3.9 or newer.")
        return ok, detail

    def _check_executable(name: str, display: str, extra_hint: str = "") -> tuple[bool, str]:
        path = shutil.which(name)
        if not path:
            hint = extra_hint or f"Install {display} and ensure it is on your PATH."
            return False, hint
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
            return False, f"Could not execute {display}: {exc}"

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"Exit code {result.returncode}"
            return False, message

        version_info = result.stdout.strip() or result.stderr.strip() or "version check succeeded"
        return True, f"Found at {path} ({version_info})."

    def _check_module(module: str, hint: str) -> tuple[bool, str]:
        if import_util.find_spec(module) is None:
            return False, hint
        return True, f"Python module '{module}' is available."

    def _check_package_version(package: str, minimum: str) -> tuple[bool, str]:
        try:
            version = metadata.version(package)
        except metadata.PackageNotFoundError:
            return False, f"Install with: pip install {package}"
        if Version(version) < Version(minimum):
            return (
                False,
                f"Detected {package} {version}. Upgrade to {minimum} or newer with "
                f"`pip install --upgrade {package}`."
            )
        return True, f"{package} {version} detected."

    all_ok &= _run_check("Python version", _check_python)
    all_ok &= _run_check("Ollama available", lambda: _check_executable("ollama", "Ollama"))
    all_ok &= _run_check(
        "pymilvus installed",
        lambda: _check_module("pymilvus", "Install with: pip install pymilvus[milvus_lite]"),
    )
    all_ok &= _run_check(
        "milvus_lite installed",
        lambda: _check_module("milvus_lite", "Install with: pip install pymilvus[milvus_lite]"),
    )
    all_ok &= _run_check(
        "langchain installed",
        lambda: _check_module("langchain", "Install with: pip install -r requirements.txt"),
    )
    all_ok &= _run_check("setuptools ≥ 81", lambda: _check_package_version("setuptools", "81"))

    data_dir = Path("data")
    all_ok &= _report(
        "Data directory present",
        data_dir.exists(),
        "Run `mkdir data` in the project root." if not data_dir.exists() else f"Using {data_dir.resolve()}",
    )

    test_script = Path("yo_full_test.sh")
    all_ok &= _report(
        "Regression script available",
        test_script.exists(),
        "Restore yo_full_test.sh from the repo root." if not test_script.exists() else "Found in project root.",
    )

    try:
        brain = YoBrain()
    except Exception as exc:  # pragma: no cover - best effort diagnosis
        all_ok &= _report(
            "YoBrain initialization",
            False,
            f"{exc}\nInstall missing dependencies or check Milvus Lite permissions.",
        )
    else:
        all_ok &= _report("YoBrain initialization", True, "Milvus Lite connection established.")

    if all_ok:
        print("\n✅ Everything looks ready! Try `python3 -m yo.cli verify` next.")
    else:
        print("\n❌ Fix the items marked above, then rerun `python3 -m yo.cli doctor`.")


def _handle_add(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain.ingest(args.path, namespace=args.ns, loader=args.loader)


def _handle_ask(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain.ask(args.question, namespace=args.ns, web=args.web)


def _handle_summarize(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain.summarize(namespace=args.ns)


def _handle_ns_list(_: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain.ns_list()


def _handle_ns_delete(args: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain.ns_delete(args.ns)


def _handle_cache_list(_: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain._list_cache()


def _handle_cache_clear(_: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain._clear_cache()


def _handle_compact(_: argparse.Namespace, brain: YoBrain | None) -> None:
    assert brain is not None
    brain.compact()


def _add_ns_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ns",
        default="default",
        help="Namespace to target (default: default)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Yo — Your Local Second Brain")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Ingest files into a namespace")
    add_parser.add_argument("path", help="Path to a file or directory to ingest")
    _add_ns_options(add_parser)
    add_parser.add_argument(
        "--loader",
        default="auto",
        help=(
            "Loader override to use (auto, text, markdown, pdf, code). "
            "Defaults to auto."
        ),
    )
    add_parser.set_defaults(handler=_handle_add)

    ask_parser = subparsers.add_parser("ask", help="Ask a question against a namespace")
    ask_parser.add_argument("question", help="Question to ask")
    _add_ns_options(ask_parser)
    ask_parser.add_argument("--web", action="store_true", help="Blend cached web context into answers")
    ask_parser.set_defaults(handler=_handle_ask)

    summarize_parser = subparsers.add_parser("summarize", help="Summarize a namespace")
    _add_ns_options(summarize_parser)
    summarize_parser.set_defaults(handler=_handle_summarize)

    ns_parser = subparsers.add_parser("ns", help="Namespace management")
    ns_sub = ns_parser.add_subparsers(dest="ns_command", required=True)

    ns_list_parser = ns_sub.add_parser("list", help="List namespaces")
    ns_list_parser.set_defaults(handler=_handle_ns_list)

    ns_delete_parser = ns_sub.add_parser("delete", help="Delete a namespace")
    _add_ns_options(ns_delete_parser)
    ns_delete_parser.set_defaults(handler=_handle_ns_delete)

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
    if args.command not in {"verify", "doctor"}:
        brain = YoBrain()

    try:
        handler(args, brain)
    except ValueError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

