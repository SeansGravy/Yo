"""Supervisory utilities for monitoring and restarting the Ollama service."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import httpx

from yo.logging_utils import get_logger
from yo.metrics import record_metric

LOGGER = get_logger(__name__)

LOG_PATH = Path("data/logs/ollama_monitor.log")
DEFAULT_INTERVAL = 15.0
DEFAULT_TIMEOUT = 5.0
SILENCE_WINDOW = timedelta(seconds=60)
OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
PING_ENDPOINT = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
PING_PAYLOAD = {"model": "llama3", "prompt": "ping"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_log_directory() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _write_log(event: str, level: str = "INFO", **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "timestamp": _utc_now().isoformat().replace("+00:00", "Z"),
        "event": event,
        "level": level.upper(),
    }
    payload.update(fields)
    try:
        _ensure_log_directory()
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except OSError as exc:
        LOGGER.warning("Unable to append Ollama monitor entry: %s", exc)
    return payload


def _log_ping_success(latency_ms: float, restart_count: int) -> None:
    _write_log("ping_success", level="INFO", latency_ms=latency_ms, restart_count=restart_count)
    record_metric("ollama_ping_latency_ms", value=round(latency_ms, 2))


def _log_ping_failure(error: str, restart_count: int) -> None:
    _write_log("ping_failure", level="WARN", error=error, restart_count=restart_count)
    record_metric("ollama_ping_failure", message=error or "unknown")


def ping_ollama(timeout: float = DEFAULT_TIMEOUT) -> Tuple[bool, float | None, str | None]:
    """Issue a lightweight generate request to Ollama."""

    start = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(PING_ENDPOINT, json=PING_PAYLOAD)
        latency_ms = (time.perf_counter() - start) * 1000.0
        if response.status_code != 200:
            return False, latency_ms, f"HTTP {response.status_code}"
        return True, latency_ms, None
    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return False, latency_ms, "timeout"
    except httpx.HTTPError as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return False, latency_ms, str(exc)


def log_ping_result(success: bool, latency_ms: float | None, error: str | None, restart_count: int) -> None:
    if success and latency_ms is not None:
        _log_ping_success(latency_ms, restart_count)
    else:
        _log_ping_failure(error or "unknown", restart_count)


def restart_ollama() -> None:
    _write_log("ollama_restart", level="WARN", message="ollama unresponsive, restarting service...")
    record_metric("ollama_restart", value=1)
    try:
        subprocess.run(["ollama", "serve", "--detach"], check=False, timeout=15)
    except Exception as exc:  # pragma: no cover - defensive path
        _write_log("ollama_restart_error", level="ERROR", message=str(exc))
        LOGGER.warning("Failed to restart Ollama: %s", exc)
        return
    _write_log("ollama_restart_requested", level="INFO", message="restart command issued")


@dataclass
class MonitorStats:
    healthy: bool
    restart_count: int
    average_latency_ms: float | None
    last_ping: datetime | None
    success_count: int
    failure_count: int

    @property
    def uptime_ratio(self) -> float | None:
        total = self.success_count + self.failure_count
        if total == 0:
            return None
        return self.success_count / total


def load_stats(window: timedelta | None = None) -> MonitorStats:
    if not LOG_PATH.exists():
        return MonitorStats(False, 0, None, None, 0, 0)

    cutoff = _utc_now() - window if window else None
    latencies: List[float] = []
    restart_count = 0
    last_ping_ts: datetime | None = None
    success = 0
    failure = 0

    with LOG_PATH.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            timestamp_str = payload.get("timestamp")
            try:
                timestamp = datetime.fromisoformat((timestamp_str or "").replace("Z", "+00:00"))
            except ValueError:
                timestamp = None

            if cutoff and timestamp and timestamp < cutoff:
                continue

            event = payload.get("event")
            if event == "ollama_restart":
                restart_count += 1
            elif event in {"ping_success", "ollama_back_online"}:
                if isinstance(payload.get("latency_ms"), (int, float)):
                    latencies.append(float(payload["latency_ms"]))
                success += 1
                if timestamp:
                    last_ping_ts = max(last_ping_ts, timestamp) if last_ping_ts else timestamp
            elif event == "ping_failure":
                failure += 1

    healthy = False
    if last_ping_ts:
        healthy = (_utc_now() - last_ping_ts) <= SILENCE_WINDOW

    avg_latency = sum(latencies) / len(latencies) if latencies else None
    return MonitorStats(
        healthy=healthy,
        restart_count=restart_count,
        average_latency_ms=avg_latency,
        last_ping=last_ping_ts,
        success_count=success,
        failure_count=failure,
    )


def run_monitor(
    *,
    interval: float = DEFAULT_INTERVAL,
    timeout: float = DEFAULT_TIMEOUT,
    watch: bool = False,
    max_cycles: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    """Continuously monitor the Ollama service, restarting on repeated failures."""

    consecutive_failures = 0
    restart_count = load_stats().restart_count
    cycles = 0

    if watch:
        print("♻️  Ollama monitor starting… (Ctrl+C to stop)")

    try:
        while max_cycles is None or cycles < max_cycles:
            success, latency_ms, error = ping_ollama(timeout=timeout)
            if success:
                if consecutive_failures > 0:
                    _write_log(
                        "ollama_back_online",
                        level="INFO",
                        latency_ms=latency_ms,
                        restart_count=restart_count,
                    )
                log_ping_result(True, latency_ms, None, restart_count)
                consecutive_failures = 0
                if watch:
                    rounded = round(latency_ms, 1) if latency_ms is not None else "n/a"
                    print(f"✅ Ollama healthy — latency {rounded} ms | restarts {restart_count}")
            else:
                consecutive_failures += 1
                log_ping_result(False, latency_ms, error, restart_count)
                if watch:
                    print(f"⚠️  Ollama ping failed ({error}); consecutive failures: {consecutive_failures}")
                if consecutive_failures >= 2:
                    restart_count += 1
                    restart_ollama()
                    consecutive_failures = 0
                    if watch:
                        print(f"♻️  Restart attempt #{restart_count} requested.")

            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            sleep_fn(interval)
    except KeyboardInterrupt:
        if watch:
            print("\nℹ️  Ollama monitor stopped.")


def format_stats(stats: MonitorStats) -> str:
    avg_latency = f"{stats.average_latency_ms:.1f} ms" if stats.average_latency_ms is not None else "n/a"
    uptime = "-"
    ratio = stats.uptime_ratio
    if ratio is not None:
        uptime = f"{ratio * 100:.1f}%"
    status = "healthy" if stats.healthy else "degraded"
    return (
        f"Ollama status: {status} | restarts: {stats.restart_count} | "
        f"avg latency: {avg_latency} | uptime (pings): {uptime}"
    )
