"""Interactive developer shell for Yo."""

from __future__ import annotations

import argparse
import cmd
import importlib
import os
import shlex
import sys
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency for nicer prompts
    import readline
except ImportError:  # pragma: no cover
    readline = None  # type: ignore[assignment]

from yo.brain import YoBrain
from yo.logging_utils import get_logger

LOGGER = get_logger(__name__)
HISTORY_PATH = Path("data/logs/shell_history.txt")


class YoShell(cmd.Cmd):
    intro = "Yo interactive shell. Type help or ? to list commands."
    prompt = "Yo> "

    def __init__(self) -> None:
        super().__init__()
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._load_history()
        self.brain = YoBrain()
        self.namespace = self.brain.active_namespace

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

        return True

    def do_EOF(self, arg: str) -> bool:  # noqa: N802 - cmd naming
        print()
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


def run_shell() -> None:
    try:
        YoShell().cmdloop()
    except KeyboardInterrupt:
        print("\nExiting shell.")


def _cli():
    return importlib.import_module("yo.cli")
