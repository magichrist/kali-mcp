"""Unit tests for the ExecutionEngine execution engine."""

from __future__ import annotations

import os

from kmcp.execution import engine


async def test_execute_success():
    r = await engine.execute(["echo", "hello world"], tool="test")
    assert r.stdout.strip() == "hello world"
    assert r.exit_code == 0
    assert r.success is True


async def test_execute_nonzero_exit_code():
    r = await engine.execute(["false"], tool="test")
    assert r.exit_code == 1
    assert r.success is False


async def test_execute_missing_binary():
    r = await engine.execute(["__nonexistent_binary_xyz__"], tool="test")
    assert r.success is False
    assert "not found" in r.stderr.lower()


async def test_execute_timeout_kills_process():
    r = await engine.execute(["sleep", "30"], tool="test", timeout=1, request_id="timeout_test")
    assert r.timed_out is True
    assert r.success is False


async def test_execute_cwd():
    r = await engine.execute(["pwd"], tool="test", cwd="/tmp")
    assert r.stdout.strip() == os.path.realpath("/tmp")


async def test_execute_env_vars():
    r = await engine.execute(
        ["bash", "-c", "echo $MCP_TEST_VAR"],
        tool="test",
        env={"MCP_TEST_VAR": "env_works"},
    )
    assert r.stdout.strip() == "env_works"
