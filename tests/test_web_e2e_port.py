from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
import websockets


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _read_optional(path: Path) -> str:
    if not path.exists():
        return "<missing>"
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        return f"<unreadable: {exc}>"


def test_web_server_e2e_port(tmp_path: Path) -> None:
    port = _find_free_port()
    health_url = f"http://127.0.0.1:{port}/api/health"
    dashboard_url = f"http://127.0.0.1:{port}/dashboard"
    chat_url = f"http://127.0.0.1:{port}/api/chat"
    ws_url = f"ws://127.0.0.1:{port}/ws/chat/e2e"

    data_dir = tmp_path / "yo-data"
    logs_dir = data_dir / "logs"
    startup_log = logs_dir / "web_startup.log"
    deadlock_dump = logs_dir / "web_deadlock.dump"
    for path in (startup_log, deadlock_dump):
        if path.exists():
            path.unlink()

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["YO_CHAT_STREAM_FALLBACK"] = "force"
    env["YO_WEB_DEBUG"] = "1"
    env["YO_DATA_DIR"] = str(data_dir)

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
        deadline = time.time() + 15
        while time.time() < deadline:
            if proc.poll() is not None:
                stdout_text, stderr_text = _shutdown()
                pytest.fail(
                    f"Server exited early (code {proc.returncode}).\nSTDOUT:\n{stdout_text}\nSTDERR:\n{stderr_text}"
                )
            try:
                response = requests.get(health_url, timeout=1)
                if response.status_code == 200 and response.json().get("status") == "ok":
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        else:
            stdout_text, stderr_text = _shutdown()
            startup_text = _read_optional(startup_log)
            deadlock_text = _read_optional(deadlock_dump)
            pytest.fail(
                "Web server failed to become healthy within 15s.\n"
                f"STDOUT:\n{stdout_text}\nSTDERR:\n{stderr_text}\n"
                f"startup log:\n{startup_text}\n"
                f"deadlock dump:\n{deadlock_text}"
            )

        resp = requests.get(dashboard_url, timeout=5)
        assert resp.status_code == 200

        chat_payload = {
            "namespace": "default",
            "message": "ping",
            "session_id": "e2e",
            "stream": True,
        }

        async def _ws_conversation() -> tuple[list[str], dict[str, object]]:
            rest_payload: dict[str, object] = {}
            async with websockets.connect(ws_url) as websocket:
                response = requests.post(chat_url, json=chat_payload, timeout=5)
                response.raise_for_status()
                rest_payload = response.json()
                messages: list[str] = []
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                    except asyncio.TimeoutError:
                        break
                    messages.append(message)
                    if "\"chat_complete\"" in message:
                        break
            return messages, rest_payload

        ws_messages, chat_result = asyncio.run(_ws_conversation())
        if not any("\"chat_complete\"" in msg for msg in ws_messages):
            assert chat_result.get("reply"), "REST fallback returned empty reply"
    finally:
        stdout_text, stderr_text = _shutdown()
