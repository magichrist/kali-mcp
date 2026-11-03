"""Integration tests for the internal PlaybookEngine (sequential + parallel steps)."""

from __future__ import annotations

import json

from kali_mcp.tools.playbook_engine import PlaybookEngine


async def test_sequential_and_parallel_playbook():
    playbook = {
        "name": "smoke-test",
        "steps": [
            {
                "parallel": False,
                "tools": [
                    {"tool": "generic_command", "args": {"command": "echo hello"}}
                ],
            },
            {
                "parallel": True,
                "tools": [
                    {"tool": "generic_command", "args": {"command": "echo a"}},
                    {"tool": "generic_command", "args": {"command": "echo b"}},
                ],
            },
        ],
    }

    res = await PlaybookEngine().run(playbook)
    payload = json.loads(res.stdout)
    assert payload["playbook"] == "smoke-test"
    results = payload["results"]
    assert isinstance(results, list) and len(results) == 3

    first = json.loads(results[0]["content"][0]["text"])
    assert first["stdout"].strip() == "hello"


async def test_failed_step_does_not_abort_playbook():
    playbook = {
        "name": "error-isolation",
        "steps": [
            {
                "parallel": False,
                "tools": [
                    {
                        "tool": "generic_command",
                        "args": {"command": "totally_fake_cmd_xyz"},
                    }
                ],
            },
            {
                "parallel": False,
                "tools": [
                    {"tool": "generic_command", "args": {"command": "echo after"}}
                ],
            },
        ],
    }

    res = await PlaybookEngine().run(playbook)
    payload = json.loads(res.stdout)
    results = payload["results"]
    assert len(results) == 2
    # The second step still executed despite the first failing
    second = json.loads(results[1]["content"][0]["text"])
    assert second["stdout"].strip() == "after"
