"""Interactive developer shell for Yo."""

from __future__ import annotations

import argparse
import cmd
import importlib
import json
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency for nicer prompts
    import readline
except ImportError:  # pragma: no cover
    readline = None  # type: ignore[assignment]

from yo.brain import YoBrain
from yo.events import publish_event
from yo import recovery

try:  # pragma: no cover - optional rich dependency
    from rich.console import Console
    from rich.panel import Panel
except ImportError:  # pragma: no cover
    Console = Panel = None

console = Console() if 'Console' in globals() and Console is not None else None
from yo.logging_utils import get_logger

LOGGER = get_logger(__name__)
HISTORY_PATH = Path("data/logs/shell_history.txt")
SHELL_LOG_DIR = recovery.SESSION_ROOT / "shell"
SHELL_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _append_shell_record(record: dict[str, Any]) -> None:
    payload = dict(record)
    payload.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
    log_path = SHELL_LOG_DIR / f"shell_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass


class YoShell(cmd.Cmd):
    intro = "Yo interactive shell. Type help or ? to list commands."
    prompt = "Yo> "

    def __init__(self) -> None:
        super().__init__()
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._load_history()

        self.console = console
        namespace_hint: str | None = None
        resume_message = ""
        resume = recovery.load_pending_shell()
        if resume:
            metadata = resume.get("metadata") or {}
            suggested_ns = metadata.get("namespace")
            resume_cwd = metadata.get("cwd")
            choice = "n"
            if sys.stdin.isatty():
                prompt_message = (
                    f"⚠️ Incomplete shell session detected (started {resume.get('created_at')}). "
                    "Resume? [y/N]: "
                )
                choice = input(prompt_message).strip().lower() or "n"
            if choice.startswith("y"):
                namespace_hint = suggested_ns
                if resume_cwd and Path(resume_cwd).exists():
                    try:
                        os.chdir(resume_cwd)
                    except OSError:
                        pass
                resume_message = "Resumed previous session context."
            else:
                resume_message = "Previous session archived."
            recovery.archive_session("shell", resume.get("session_id"))

        self.brain = YoBrain(namespace=namespace_hint)
        self.namespace = self.brain.active_namespace
        if namespace_hint and namespace_hint != self.namespace:
            try:
                self.brain.ns_switch(namespace_hint)
                self.namespace = namespace_hint
            except Exception:  # pragma: no cover - defensive guard
                pass

        self.recovery_session_id = recovery.start_session(
            "shell",
            {
                "namespace": self.namespace,
                "cwd": os.getcwd(),
            },
        )
        _append_shell_record(
            {
                "event": "start",
                "session_id": self.recovery_session_id,
                "namespace": self.namespace,
                "cwd": os.getcwd(),
            }
        )
        publish_event(
            "shell_start",
            {
                "session_id": self.recovery_session_id,
                "namespace": self.namespace,
                "cwd": os.getcwd(),
            },
        )
        self._session_closed = False
        self._update_prompt()
        banner = f"🛠️ Yo Shell ready — namespace: {self.namespace}"
        if self.console and Panel:
            self.console.print(Panel.fit(banner, border_style="cyan"))
        else:
            print(banner)
        if resume_message:
            print(f"ℹ️ {resume_message}")

    # ------------------------------------------------------------------
    # Chat helpers
    # ------------------------------------------------------------------
    def _send_chat(self, message: str, *, stream: bool = False) -> None:
        args = argparse.Namespace(message=[message], ns=self.namespace, web=False, stream=stream)
        _cli()._handle_chat(args, self.brain)

    # ------------------------------------------------------------------
    # Built-in commands
    # ------------------------------------------------------------------
    def do_chat(self, arg: str) -> None:
        """chat <message>

        Send a chat message to YoBrain. Use `--stream` to stream tokens."""

        tokens = shlex.split(arg)
        if not tokens:
            print("Usage: chat [--stream] <message>")
            return
        stream = False
        if tokens[0] == "--stream":
            stream = True
            tokens = tokens[1:]
        if not tokens:
            print("Message required.")
            return
        message = " ".join(tokens)
        self._send_chat(message, stream=stream)

    def do_namespace(self, arg: str) -> None:
        """namespace <name>

        Switch the active namespace for subsequent commands."""

        tokens = shlex.split(arg)
        if not tokens:
            print(f"Current namespace: {self.namespace}")
            return
        name = tokens[0]
        self.namespace = name
        self._update_prompt()
        print(f"Namespace set to {self.namespace}")

    def do_verify(self, arg: str) -> None:
        """verify

        Run the verification suite."""

        try:
            _cli().run_test(argparse.Namespace())
        except SystemExit:
            pass

    def do_telemetry(self, arg: str) -> None:
        """telemetry

        Display recent telemetry stats."""

        try:
            _cli()._handle_telemetry_report(argparse.Namespace(json=False, release=False, days=7))
        except SystemExit:
            pass

    def do_deps(self, arg: str) -> None:
        """deps check

        Run dependency diagnostics."""

        tokens = shlex.split(arg)
        if tokens and tokens[0] == "check":
            try:
                _cli()._handle_deps_check(argparse.Namespace())
            except SystemExit:
                pass
        else:
            print("Usage: deps check")

    def do_config(self, arg: str) -> None:
        """config [get|set] ...

        Manage configuration values."""

        tokens = shlex.split(arg)
        if not tokens or tokens[0] == "get":
            ns = tokens[1] if len(tokens) > 1 else None
            try:
                _cli()._handle_config_view(argparse.Namespace(ns=ns), None)
            except SystemExit:
                pass
            return
        if tokens[0] == "set" and len(tokens) >= 3:
            key, value = tokens[1], tokens[2]
            ns = tokens[3] if len(tokens) > 3 else None
            try:
                _cli()._handle_config_set(argparse.Namespace(key=key, value=value, ns=ns), None)
            except SystemExit:
                pass
            return
        print("Usage: config get [namespace]\n       config set <key> <value> [namespace]")

    def do_dashboard(self, arg: str) -> None:
        """dashboard [--live] [--events]

        Mirror the CLI dashboard."""

        tokens = shlex.split(arg)
        args = argparse.Namespace(live="--live" in tokens, events="--events" in tokens)
        try:
            _cli()._handle_dashboard_cli(args, None)
        except SystemExit:
            pass

    def do_exit(self, arg: str) -> bool:  # noqa: D401 - cmd requirement
        """Exit the shell."""

        self._close_session()
        return True

    def do_EOF(self, arg: str) -> bool:  # noqa: N802 - cmd naming
        print()
        self._close_session()
        return True

    # ------------------------------------------------------------------
    # History helpers
    # ------------------------------------------------------------------
    def _load_history(self) -> None:
        if readline is None:
            return
        if HISTORY_PATH.exists():
            try:
                readline.read_history_file(str(HISTORY_PATH))
            except OSError:
                pass

    def postcmd(self, stop: bool, line: str) -> bool:
        if readline is not None:
            try:
                readline.write_history_file(str(HISTORY_PATH))
            except OSError:
                pass
        return super().postcmd(stop, line)

    def onecmd(self, line: str) -> bool:
        result = super().onecmd(line)
        if line.strip():
            self._log_command(line)
        return result

    def _log_command(self, line: str) -> None:
        session_id = getattr(self, "recovery_session_id", None)
        if not session_id:
            return
        record = {
            "event": "command",
            "session_id": session_id,
            "command": line,
            "namespace": self.namespace,
            "cwd": os.getcwd(),
        }
        _append_shell_record(record)
        publish_event("shell_command", record)
        recovery.update_session(
            "shell",
            session_id,
            {
                "namespace": self.namespace,
                "cwd": os.getcwd(),
                "last_command": line,
            },
        )

    def _update_prompt(self) -> None:
        self.prompt = f"Yo[{self.namespace}]> "

    def _close_session(self) -> None:
        if getattr(self, "_session_closed", False):
            return
        self._session_closed = True
        session_id = getattr(self, "recovery_session_id", None)
        if session_id:
            recovery.complete_session("shell", session_id)
            _append_shell_record(
                {
                    "event": "end",
                    "session_id": session_id,
                    "namespace": self.namespace,
                    "cwd": os.getcwd(),
                }
            )
            publish_event(
                "shell_end",
                {
                    "session_id": session_id,
                    "namespace": self.namespace,
                    "cwd": os.getcwd(),
                },
            )
            self.recovery_session_id = None

    def close_session(self) -> None:
        self._close_session()


def run_shell() -> None:
    shell = YoShell()
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print("\nExiting shell.")
    finally:
        shell.close_session()


def _cli():
    return importlib.import_module("yo.cli")
