"""Integration tests for parallel_execute aggregation and parallel_status."""

from __future__ import annotations

import json

from tools.parallel_execute import ParallelExecuteTool, ParallelStatusTool


async def test_parallel_execution_with_aggregation():
    t = ParallelExecuteTool()
    result = await t.safe_execute(
        {
            "target": "127.0.0.1",
            "tools": [
                {"tool": "generic_command", "args": {"command": "echo one"}},
                {"tool": "generic_command", "args": {"command": "echo two"}},
            ],
            "max_concurrent": 2,
        }
    )
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    stdout = json.loads(payload["stdout"])
    assert stdout["job_id"]
    assert len(stdout["results"]) == 2
    assert "aggregate" in stdout


async def test_error_isolation():
    t = ParallelExecuteTool()
    result = await t.safe_execute(
        {
            "target": "127.0.0.1",
            "tools": [
                {"tool": "generic_command", "args": {"command": "totally_fake_cmd"}},
                {"tool": "generic_command", "args": {"command": "echo survivor"}},
            ],
        }
    )
    payload = json.loads(result["content"][0]["text"])
    stdout = json.loads(payload["stdout"])
    # The second tool still completed
    assert len(stdout["results"]) == 2


async def test_parallel_status():
    t = ParallelExecuteTool()
    result = await t.safe_execute(
        {
            "target": "127.0.0.1",
            "tools": [{"tool": "generic_command", "args": {"command": "echo x"}}],
        }
    )
    stdout = json.loads(json.loads(result["content"][0]["text"])["stdout"])
    job_id = stdout["job_id"]

    status = await ParallelStatusTool().safe_execute({"job_id": job_id})
    assert status["isError"] is False
    data = json.loads(status["content"][0]["text"])
    jobs = json.loads(data["stdout"])["jobs"]
    assert jobs[job_id]["status"] == "completed"
    assert jobs[job_id]["done"] == 1

    # Unknown job → structured error
    bad = await ParallelStatusTool().safe_execute({"job_id": "nope"})
    assert bad["isError"] is True
