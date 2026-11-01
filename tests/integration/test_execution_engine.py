"""Integration tests for the hardened subprocess execution engine."""

from __future__ import annotations

import os

from execution import engine


async def test_successful_command():
    r = await engine.execute(["echo", "hello world"], tool="test")
    assert r.stdout.strip() == "hello world"
    assert r.exit_code == 0
    assert r.success is True
    assert r.timed_out is False
    assert r.duration > 0
    assert r.start_time


async def test_nonzero_exit_code():
    r = await engine.execute(["false"], tool="test")
    assert r.exit_code == 1
    assert r.success is False


async def test_missing_binary():
    r = await engine.execute(["__nonexistent_binary_xyz__"], tool="test")
    assert r.success is False
    assert "not found" in r.stderr.lower()


async def test_timeout_kills_process():
    r = await engine.execute(
        ["sleep", "30"], tool="test", timeout=1, request_id="timeout_test"
    )
    assert r.timed_out is True
    assert r.success is False


async def test_cwd_parameter():
    r = await engine.execute(["pwd"], tool="test", cwd="/tmp")
    assert r.stdout.strip() == os.path.realpath("/tmp")


async def test_env_variables_passed():
    r = await engine.execute(
        ["bash", "-c", "echo $MCP_TEST_VAR"],
        tool="test",
        env={"MCP_TEST_VAR": "env_works"},
    )
    assert r.stdout.strip() == "env_works"


async def test_stderr_captured():
    r = await engine.execute(["bash", "-c", "echo err_msg >&2"], tool="test")
    assert "err_msg" in r.stderr


async def test_shell_metacharacters_via_bash():
    r = await engine.execute(
        ["bash", "-c", "echo a && echo b; echo {x,y}"], tool="test"
    )
    lines = r.stdout.strip().split("\n")
    assert lines[0] == "a" and lines[1] == "b"
    assert "x" in lines[2] and "y" in lines[2]
