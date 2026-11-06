"""Integration tests for playbook engine state tracking, resume, and status tools."""

from __future__ import annotations

import json

import pytest

from kali_mcp.tools.playbook_engine import RUN_STATUS, PlaybookEngine


@pytest.fixture(autouse=True)
def _clean_run_status():
    RUN_STATUS.clear()
    yield
    RUN_STATUS.clear()


def _two_step_playbook() -> dict:
    return {
        "name": "resume-test",
        "steps": [
            {
                "id": "step1",
                "parallel": False,
                "tools": [{"tool": "generic_command", "args": {"command": "echo one"}}],
            },
            {
                "id": "step2",
                "parallel": False,
                "tools": [{"tool": "generic_command", "args": {"command": "echo two"}}],
            },
        ],
    }


async def test_run_records_status():
    res = await PlaybookEngine().run(_two_step_playbook())
    state = RUN_STATUS["resume-test"]
    assert state["status"] == "completed"
    assert state["completed_steps"] == [0, 1]
    payload = json.loads(res.stdout)
    assert payload["status"] == "completed"


async def test_target_placeholder_substitution():
    playbook = {
        "name": "subst-test",
        "target": "10.5.5.5",
        "steps": [
            {
                "id": "step1",
                "parallel": False,
                "tools": [{"tool": "generic_command", "args": {"command": "echo {{target}}"}}],
            },
        ],
    }
    res = await PlaybookEngine().run(playbook)
    payload = json.loads(res.stdout)
    out = json.loads(payload["results"][0]["content"][0]["text"])
    assert out["stdout"].strip() == "10.5.5.5"


async def test_resume_skips_completed_steps():
    # Simulate an interrupted run: step 0 completed, step 1 never ran
    RUN_STATUS["resume-test"] = {"status": "partial", "completed_steps": [0]}
    engine = PlaybookEngine()
    res = await engine.run(_two_step_playbook(), resume=True)
    payload = json.loads(res.stdout)
    assert len(payload["results"]) == 1
    out = json.loads(payload["results"][0]["content"][0]["text"])
    assert out["stdout"].strip() == "two"
    state = RUN_STATUS["resume-test"]
    assert state["completed_steps"] == [0, 1]
    assert state["status"] == "completed"


async def test_playbook_status_tool():
    from kali_mcp.tools.playbook_tools import PlaybookStatusTool

    await PlaybookEngine().run(_two_step_playbook())
    result = await PlaybookStatusTool().safe_execute({"name": "resume-test"})
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    assert data["stdout"]  # payload present

    # Unknown name → structured error
    result = await PlaybookStatusTool().safe_execute({"name": "nope"})
    assert result["isError"] is True


async def test_playbook_list_tool():
    from kali_mcp.tools.playbook_tools import PlaybookListTool

    result = await PlaybookListTool().safe_execute({})
    assert result["isError"] is False
    data = json.loads(result["content"][0]["text"])
    payload = json.loads(data["stdout"])
    assert set(payload["playbooks"]) >= {
        "playbook_recon",
        "playbook_webapp",
        "playbook_ad",
    }


async def test_playbook_engine_tool_validates():
    from kali_mcp.tools.playbook_engine_tool import PlaybookEngineTool

    t = PlaybookEngineTool()
    result = await t.safe_execute({"playbook": {"name": "x", "steps": []}})
    assert result["isError"] is True  # empty steps rejected

    result = await t.safe_execute(
        {
            "playbook": {
                "name": "ok",
                "steps": [
                    {
                        "id": "step1",
                        "parallel": False,
                        "tools": [{"tool": "generic_command", "args": {"command": "echo ok"}}],
                    }
                ],
            }
        }
    )
    assert result["isError"] is False
