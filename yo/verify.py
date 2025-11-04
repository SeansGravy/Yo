"""Helpers for Yo verification workflows."""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Sequence


SUMMARY_LINE_PATTERN = re.compile(r"=+ (.+) =+")


def _ensure_logs_dir() -> Path:
    path = Path("data/logs")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_pytest_summary(summary_text: str) -> Dict[str, Any]:
    summary_line: str | None = None
    for raw in reversed(summary_text.splitlines()):
        line = raw.strip()
        if " in " in line and ("passed" in line or "failed" in line or "error" in line):
            summary_line = line
            break

    metrics: Dict[str, Any] = {}

    if not summary_line:
        return metrics

    match = SUMMARY_LINE_PATTERN.match(summary_line)
    body = match.group(1) if match else summary_line.strip("=").strip()

    if " in " in body:
        counts_part, duration_part = body.rsplit(" in ", 1)
    else:
        counts_part, duration_part = body, ""

    counts: Dict[str, int] = {}
    for part in counts_part.split(","):
        chunk = part.strip()
        count_match = re.match(r"(?P<count>\d+)\s+(?P<label>[A-Za-z_]+)", chunk)
        if not count_match:
            continue
        label = count_match.group("label").lower()
        count = int(count_match.group("count"))
        counts[label] = count

    if duration_part:
        dur_match = re.search(r"([0-9]+\.?[0-9]*)s", duration_part)
        if dur_match:
            metrics["duration_seconds"] = float(dur_match.group(1))

    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0)
    skipped = counts.get("skipped", 0)
    xfailed = counts.get("xfailed", 0)
    xpassed = counts.get("xpassed", 0)
    deselected = counts.get("deselected", 0)

    total = passed + failed + skipped + xfailed + xpassed + deselected

    metrics.update(
        {
            "tests_total": total,
            "tests_passed": passed,
            "tests_failed": failed,
            "tests_skipped": skipped,
            "tests_xfailed": xfailed,
            "tests_xpassed": xpassed,
            "tests_deselected": deselected,
            "raw_summary": summary_line,
        }
    )
    return metrics


def run_pytest_with_metrics(args: Sequence[str] | None = None) -> tuple[int, Dict[str, Any], str]:
    """Execute pytest, stream the output, and return metrics."""

    command = ["python3", "-m", "pytest"]
    if args:
        command.extend(args)

    print("▶️ Running pytest for telemetry...")
    start = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    output_chunks: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        output_chunks.append(line)

    process.wait()
    duration = time.perf_counter() - start

    full_output = "".join(output_chunks)
    metrics = _parse_pytest_summary(full_output)
    metrics.setdefault("duration_seconds", round(duration, 3))
    metrics.setdefault("tests_total", 0)
    metrics.setdefault("tests_passed", 0)
    metrics.setdefault("tests_failed", 0)
    metrics.setdefault("raw_summary", "")

    return process.returncode, metrics, full_output


def _append_history(entry: Dict[str, Any]) -> None:
    logs_dir = _ensure_logs_dir()
    history_path = logs_dir / "test_history.json"
    history: list[Dict[str, Any]]
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            history = []
    else:
        history = []

    history.append(entry)
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")


def _write_badge(summary: Dict[str, Any]) -> None:
    logs_dir = _ensure_logs_dir()
    badge_path = logs_dir / "badge.md"
    status = summary.get("status", "")
    tests_total = summary.get("tests_total", 0) or 0
    passed = summary.get("tests_passed", 0) or 0
    pass_rate = summary.get("pass_rate")

    if pass_rate is None and tests_total:
        pass_rate = passed / tests_total if tests_total else 0.0

    if pass_rate is None:
        pass_rate = 0.0

    if isinstance(pass_rate, str):
        try:
            pass_rate = float(pass_rate)
        except ValueError:
            pass_rate = 0.0

    if status.startswith("✅"):
        color = "brightgreen" if pass_rate >= 0.99 else "yellow"
        label = "passing"
    else:
        color = "red"
        label = "failing"

    badge = f"![Tests](https://img.shields.io/badge/tests-{label}-{color})\n"
    badge_path.write_text(badge, encoding="utf-8")


def write_test_summary(result: str = "✅ Verify successful", **extra: Any) -> Dict[str, Any]:
    """Persist a summary of the latest verification run and update telemetry artifacts."""

    logs_dir = _ensure_logs_dir()
    summary: Dict[str, Any] = {
        "timestamp": datetime.datetime.now().isoformat(),
        "status": result,
    }
    if extra:
        summary.update(extra)

    tests_total = summary.get("tests_total")
    tests_passed = summary.get("tests_passed")
    if tests_total:
        pass_rate = tests_passed / tests_total if tests_total else 0
        summary["pass_rate"] = pass_rate

    summary_path = logs_dir / "test_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _append_history(summary)
    _write_badge(summary)
    print(f"[Yo] Test summary written: {summary['timestamp']} -> {summary_path}")
    return summary


__all__ = ["run_pytest_with_metrics", "write_test_summary"]
