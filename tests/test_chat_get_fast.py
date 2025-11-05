from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_server(port: int, data_dir: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["YO_DATA_DIR"] = str(data_dir)
    env["YO_WEB_DEBUG"] = "0"
    env["YO_CHAT_STREAM_FALLBACK"] = "force"
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [sys.executable, "-m", "yo.cli", "web", "--host", "127.0.0.1", "--port", str(port)]
    return subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _wait_for_health(port: int, timeout: float = 15.0) -> bool:
    health_url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(health_url, timeout=1)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return True
        except requests.RequestException:
            pass
        time.sleep(0.3)
    return False


def _shutdown(proc: subprocess.Popen[str]) -> tuple[str, str]:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
    return stdout_bytes.decode(errors="ignore"), stderr_bytes.decode(errors="ignore")


@pytest.mark.timeout(90)
def test_chat_get_returns_html_under_one_second(tmp_path: Path) -> None:
    port = _find_free_port()
    data_dir = tmp_path / "yo-data"
    proc = _start_server(port, data_dir)

    try:
        assert _wait_for_health(port), "Server failed health check."
        chat_url = f"http://127.0.0.1:{port}/chat"
        started = time.time()
        response = requests.get(chat_url, timeout=2)
        elapsed = time.time() - started
        assert response.status_code == 200, response.text
        assert "text/html" in response.headers.get("Content-Type", "")
        assert elapsed < 1.0, f"/chat responded in {elapsed:.2f}s (expected < 1s)"
    finally:
        stdout_text, stderr_text = _shutdown(proc)
        if proc.returncode not in (0, None, -15, -9):
            pytest.fail(
                f"Web server exited unexpectedly with code {proc.returncode}.\nSTDOUT:\n{stdout_text}\nSTDERR:\n{stderr_text}"
            )
