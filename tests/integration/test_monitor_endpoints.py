"""Integration tests for the monitor HTTP endpoints (SSE stream + action POST).

Spawns a real server process and uses raw HTTP (httpx) to verify:
  - GET /monitor/stream returns SSE snapshots
  - POST /monitor/action supports get_snapshot, force_cleanup, kill_job
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url():
    """Start the MCP server on a free port; yield its base URL; shut it down."""
    port = _free_port()
    env = {
        **__import__("os").environ,
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(port),
        "MCP_TRANSPORT": "streamable-http",
        "MCP_DEBUG": "false",
        "MCP_DB_ENABLED": "false",
        # Monitor tests do not exercise auth; opt out of the token requirement
        # so the dev server starts without MCP_API_TOKEN.
        "KALI_MCP_INSECURE": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "src" / "kali_mcp" / "server.py")],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        last_err: Exception | None = None
        for _ in range(60):
            if proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
                raise RuntimeError(f"server exited early:\n{out[-2000:]}")
            try:
                httpx.get(f"{base}/mcp", timeout=1)
                last_err = None
                break
            except Exception:  # noqa: BLE001 — connection refused until ready
                last_err = None  # reset on each attempt
                time.sleep(0.5)
        if last_err is not None:
            raise RuntimeError(f"server did not become ready: {last_err}")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_monitor_get_snapshot(server_url):
    """POST /monitor/action with get_snapshot returns current state."""
    resp = httpx.post(
        f"{server_url}/monitor/action",
        json={"action": "get_snapshot"},
        timeout=5,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "timestamp" in data
    assert "sessions" in data
    assert "jobs" in data
    assert "health" in data
    assert data["health"]["status"] == "healthy"


def test_monitor_force_cleanup(server_url):
    """POST /monitor/action with force_cleanup returns cleaned count."""
    resp = httpx.post(
        f"{server_url}/monitor/action",
        json={"action": "force_cleanup"},
        timeout=5,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "force_cleanup"
    assert "cleaned" in data


def test_monitor_kill_job_unknown(server_url):
    """POST /monitor/action with kill_job for unknown job returns killed=False."""
    resp = httpx.post(
        f"{server_url}/monitor/action",
        json={"action": "kill_job", "request_id": "does-not-exist"},
        timeout=5,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "kill_job"
    assert data["killed"] is False


def test_monitor_unknown_action(server_url):
    """POST /monitor/action with unknown action returns 400."""
    resp = httpx.post(
        f"{server_url}/monitor/action",
        json={"action": "bogus"},
        timeout=5,
    )
    assert resp.status_code == 400


def test_monitor_stream_sse(server_url):
    """GET /monitor/stream returns SSE-formatted snapshots."""
    with httpx.stream("GET", f"{server_url}/monitor/stream", timeout=10) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        data_lines = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                data_lines.append(line)
                if len(data_lines) >= 2:
                    break  # Got enough — close the stream

    assert len(data_lines) >= 1, "expected at least one SSE data line"

    # First line should be valid JSON
    first_json = data_lines[0][len("data: ") :]
    payload = json.loads(first_json)
    assert "timestamp" in payload
    assert "sessions" in payload
    assert "jobs" in payload
    assert "health" in payload
