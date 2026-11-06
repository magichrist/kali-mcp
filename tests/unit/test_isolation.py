"""Unit tests for the execution-isolation guard (src/kali_mcp/isolation.py).

These tests run in-process and exercise the best-effort per-step resource
caps: wall-clock timeout enforcement (every platform) and rlimit-based
limits (Linux only; skipped gracefully on macOS).
"""

from __future__ import annotations

import asyncio
import platform

import pytest

from kali_mcp.isolation import StepLimits, isolation_available, spawn_isolated


def test_isolation_available_flag_is_bool():
    assert isinstance(isolation_available(), bool)


@pytest.mark.asyncio
async def test_spawn_isolated_runs_command():
    code, out, err, dur = await spawn_isolated(["echo", "isolated-ok"])
    assert code == 0
    assert "isolated-ok" in out
    assert dur >= 0


@pytest.mark.asyncio
async def test_spawn_isolated_enforces_timeout():
    code, out, err, dur = await spawn_isolated(
        ["sleep", "30"], StepLimits(timeout=1)
    )
    assert code == -1
    assert "Timed out after 1s" in err
    # The timeout must actually be honored (not 30s).
    assert dur < 5


@pytest.mark.asyncio
async def test_spawn_isolated_missing_binary():
    code, out, err, dur = await spawn_isolated(["__no_such_binary_xyz__"])
    assert code == -1
    assert "not found" in err


@pytest.mark.skipif(platform.system() != "Linux", reason="rlimits only enforce on Linux")
@pytest.mark.asyncio
async def test_spawn_isolated_applies_rlimits_on_linux():
    # A tiny memory cap that a simple echo still fits under.
    code, out, err, dur = await spawn_isolated(
        ["echo", "rlimit-ok"],
        StepLimits(timeout=5, max_memory_bytes=256 * 1024 * 1024, max_open_files=64),
    )
    assert code == 0
    assert "rlimit-ok" in out


@pytest.mark.asyncio
async def test_spawn_isolated_string_command():
    code, out, err, dur = await spawn_isolated("echo string-cmd", StepLimits(timeout=5))
    assert code == 0
    assert "string-cmd" in out
