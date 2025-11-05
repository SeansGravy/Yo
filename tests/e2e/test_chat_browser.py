from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import Error, sync_playwright
import requests


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_health(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=1)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Service at {url} failed health check within {timeout}s")


@pytest.mark.timeout(90)
def test_chat_browser(tmp_path: Path) -> None:
    port = _find_free_port()
    health_url = f"http://127.0.0.1:{port}/api/health"
    chat_url = f"http://127.0.0.1:{port}/api/chat"
    data_dir = tmp_path / "yo-data"

    env = os.environ.copy()
    env["YO_DATA_DIR"] = str(data_dir)
    env["YO_WEB_DEBUG"] = "1"
    env["YO_CHAT_STREAM_FALLBACK"] = "force"
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [sys.executable, "-m", "yo.cli", "web", "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _shutdown() -> tuple[str, str]:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
        return stdout_bytes.decode(errors="ignore"), stderr_bytes.decode(errors="ignore")

    try:
        _wait_for_health(health_url)

        with sync_playwright() as playwright:
            browser = None
            try:
                browser = playwright.chromium.launch(headless=True)
            except Error as exc:  # pragma: no cover - dependent on local setup
                if "playwright install" in str(exc).lower():
                    pytest.skip("Playwright browsers not installed. Run `playwright install chromium`.")
                raise

            try:
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{port}/chat?debug=1", wait_until="networkidle")
                page.fill("#message-input", "ping")
                page.click("#send-button")
                page.wait_for_selector(".assistant .assistant-text", timeout=10000)
                assistant_text = page.inner_text(".assistant .assistant-text:last-of-type").strip()
                status_text = page.inner_text("#status").strip()
                assert assistant_text, f"Empty assistant reply (status: {status_text})"
                assert "disconnected" not in status_text.lower()
            finally:
                if browser is not None:
                    browser.close()

        response = requests.post(
            chat_url,
            json={"namespace": "default", "message": "ping", "session_id": "playwright-probe", "stream": False},
            timeout=5,
        )
        response.raise_for_status()
        assert (response.json().get("reply") or "").strip()
    finally:
        stdout_text, stderr_text = _shutdown()
        if proc.returncode not in (0, None, -15, -9):
            pytest.fail(
                f"Web server exited with code {proc.returncode}.\nSTDOUT:\n{stdout_text}\nSTDERR:\n{stderr_text}"
            )
