"""Coverage-focused unit tests for ``src/kali_mcp/tools/playbook_blackbox.py``.

Covers:
  - tool schema (input_schema), validate, execute and safe_execute
  - playbook ``run()`` paths: background (job accepted) and foreground (result)
  - helpers: _new_id, _payload, _truncate_payload, _success_tool_result
  - playbook_result lookup: in-memory registry and vault fallback
  - job status/error reflection in the registry
  - error paths: missing keys, unknown playbook, validation errors, not found
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kali_mcp.tools.playbook_blackbox import (
    JOB_REGISTRY,
    PlaybookCatalogTool,
    PlaybookResultTool,
    PlaybookRunTool,
    _new_id,
    _payload,
    _success_tool_result,
    _truncate_payload,
)


@pytest.fixture(autouse=True)
def _clear_job_registry():
    JOB_REGISTRY.clear()
    yield
    JOB_REGISTRY.clear()


def _engine(assessment: dict[str, Any]) -> MagicMock:
    eng = MagicMock()
    eng.execute = AsyncMock(return_value=assessment)
    return eng


def _tool_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Unwrap an MCP tool result into the tool payload dict."""
    return json.loads(json.loads(result["content"][0]["text"])["stdout"])


# ── helpers ───────────────────────────────────────────────────────────


def test_new_id_shape():
    jid = _new_id("job")
    aid = _new_id("assessment")
    assert jid.startswith("job_") and len(jid) == len("job_") + 12
    assert aid.startswith("assessment_") and len(aid) == len("assessment_") + 12
    assert jid != aid


def test_payload_identity():
    assert _payload({"x": 1}) == {"x": 1}


def test_success_tool_result():
    res = _success_tool_result("playbook_run", {"a": 1}, exit_code=0)
    assert res["isError"] is False
    payload = json.loads(res["content"][0]["text"])
    assert payload["success"] is True
    assert payload["tool"] == "playbook_run"
    assert json.loads(payload["stdout"]) == {"a": 1}


def test_truncate_payload_under_limit():
    assessment = {"evidence": {"k": "v"}, "module_results": {"m": {}}}
    _truncate_payload(assessment, limit=10_000)
    assert assessment == {"evidence": {"k": "v"}, "module_results": {"m": {}}}


def test_truncate_payload_over_limit_dict_nodes():
    assessment = {
        "evidence": {f"k{i}": i for i in range(20)},
        "module_results": {f"m{i}": i for i in range(20)},
    }
    _truncate_payload(assessment, limit=10)  # force over the limit
    assert len(assessment["evidence"]) <= 3
    assert len(assessment["module_results"]) <= 3


def test_truncate_payload_over_limit_nondict_nodes():
    assessment = {"evidence": [1, 2, 3], "module_results": "not-a-dict"}
    _truncate_payload(assessment, limit=10)
    # non-dict nodes are skipped, no crash
    assert assessment["evidence"] == [1, 2, 3]
    assert assessment["module_results"] == "not-a-dict"


# ── PlaybookRunTool ───────────────────────────────────────────────────


class TestPlaybookRunTool:
    def test_properties(self):
        tool = PlaybookRunTool()
        assert tool.name == "playbook_run"
        assert tool.description
        assert tool.default_timeout == 3600

    def test_input_schema(self):
        tool = PlaybookRunTool()
        schema = tool.input_schema()
        assert schema["type"] == "object"
        assert set(schema["required"]) == {"playbook", "target"}
        assert "playbook" in schema["properties"]
        assert "target" in schema["properties"]

    def test_build_command(self):
        tool = PlaybookRunTool()
        assert tool.build_command({"playbook": "pb", "target": "t"}) == [
            "playbook_run",
            "pb",
            "t",
        ]

    @pytest.mark.parametrize(
        "args,err",
        [
            ({}, "playbook is required"),
            ({"target": "t"}, "playbook is required"),
            ({"playbook": "pb"}, "target is required"),
            (
                {"playbook": "pb", "target": "t", "profile": "bogus"},
                "profile must be",
            ),
            (
                {"playbook": "pb", "target": "t", "detail": "bogus"},
                "detail must be",
            ),
        ],
    )
    def test_validate_rejects(self, args, err):
        tool = PlaybookRunTool()
        with pytest.raises(ValueError, match=err):
            tool.validate(args)

    def test_validate_unknown_playbook(self):
        tool = PlaybookRunTool()
        with patch(
            "kali_mcp.playbooks.registry.get_playbook", side_effect=KeyError("nope")
        ):
            with pytest.raises(ValueError, match="unknown playbook"):
                tool.validate({"playbook": "pb", "target": "t"})

    def test_validate_known_playbook(self):
        tool = PlaybookRunTool()
        with patch(
            "kali_mcp.playbooks.registry.get_playbook", return_value={"id": "pb"}
        ):
            tool.validate({"playbook": "pb", "target": "t"})  # does not raise

    async def test_execute_background_accepted(self):
        tool = PlaybookRunTool()
        assessment = {
            "assessment_id": "assessment_abc",
            "execution": {"status": "completed"},
            "assets": {},
            "findings": [],
            "correlated_findings": [],
            "asset_graph": {},
            "next_actions": [],
            "summary": {"assets": 0, "findings": 0},
        }
        with patch(
            "kali_mcp.playbooks.registry.get_playbook",
            return_value={"execution": {"timeout": 600}},
        ), patch("kali_mcp.playbooks.engine.PlaybookEngine", return_value=_engine(assessment)):
            result = await tool.execute(
                {"playbook": "pb", "target": "t", "background": True}
            )
            # let the scheduled background task run while the engine is mocked
            await asyncio.sleep(0)

        assert result["isError"] is False
        payload = result["assessment_run"]
        assert payload["status"] == "accepted"
        assert payload["job_id"].startswith("job_")
        assert payload["assessment_id"].startswith("assessment_")
        assert result["assessment_run"] is payload

        entry = JOB_REGISTRY[payload["job_id"]]
        assert entry["status"] == "completed"
        assert entry["result"] == assessment

    async def test_execute_foreground_full_detail(self):
        tool = PlaybookRunTool()
        assessment = {
            "assessment_id": "assessment_def",
            "execution": {"status": "completed"},
            "assets": {"hosts": [{"ip": "127.0.0.1"}]},
            "findings": [{"severity": "high"}],
            "correlated_findings": [],
            "asset_graph": {"nodes": []},
            "next_actions": ["act"],
            "summary": {"assets": 1, "findings": 1},
            "evidence": {"e": 1},
            "coverage": {"c": 1},
            "module_results": {"m": 1},
        }
        with patch(
            "kali_mcp.playbooks.registry.get_playbook",
            return_value={"execution": {"timeout": 10}},
        ), patch("kali_mcp.playbooks.engine.PlaybookEngine", return_value=_engine(assessment)):
            result = await tool.execute(
                {"playbook": "pb", "target": "t", "detail": "full"}
            )

        assert result["isError"] is False
        ar = result["assessment_run"]
        assert ar["status"] == "completed"
        assert ar["assets"] == {"hosts": [{"ip": "127.0.0.1"}]}
        assert ar["findings"] == [{"severity": "high"}]
        assert ar["correlated_findings"] == []
        assert ar["asset_graph"] == {"nodes": []}
        assert ar["next_actions"] == ["act"]
        assert ar["summary"] == {"assets": 1, "findings": 1}
        assert ar["assessment_id"] == "assessment_def"
        assert set(ar["context"]) == {"evidence", "coverage", "module_results"}

    async def test_execute_foreground_minimal_assessment_fallbacks(self):
        tool = PlaybookRunTool()
        # empty assessment: execution not a dict, missing summary/ids/etc.
        with patch(
            "kali_mcp.playbooks.registry.get_playbook",
            return_value={"execution": {"timeout": 10}},
        ), patch(
            "kali_mcp.playbooks.engine.PlaybookEngine", return_value=_engine({})
        ):
            result = await tool.execute({"playbook": "pb", "target": "t"})

        assert result["isError"] is False
        ar = result["assessment_run"]
        assert ar["status"] == "completed"  # execution not a dict -> "completed"
        assert ar["summary"] == {"assets": 0, "findings": 0}  # default summary
        assert ar["assets"] == {}
        assert ar["findings"] == []
        assert ar["assessment_id"].startswith("assessment_")  # fallback id
        assert "context" not in ar  # detail not full -> no context key

    async def test_execute_unknown_playbook_raises(self):
        tool = PlaybookRunTool()
        with patch(
            "kali_mcp.playbooks.registry.get_playbook", side_effect=KeyError("nope")
        ), patch("kali_mcp.playbooks.engine.PlaybookEngine", return_value=_engine({})):
            with pytest.raises(KeyError):
                await tool.execute({"playbook": "nope", "target": "t"})

    async def test_safe_execute_success(self):
        tool = PlaybookRunTool()
        tool._skip_central_persist = True
        with patch(
            "kali_mcp.playbooks.registry.get_playbook",
            return_value={"execution": {"timeout": 10}},
        ), patch(
            "kali_mcp.playbooks.engine.PlaybookEngine", return_value=_engine({})
        ):
            result = await tool.safe_execute({"playbook": "pb", "target": "t"})
        assert result["isError"] is False

    async def test_safe_execute_catches_execute_error(self):
        tool = PlaybookRunTool()
        tool._skip_central_persist = True
        with patch(
            "kali_mcp.playbooks.registry.get_playbook", side_effect=KeyError("x")
        ), patch("kali_mcp.playbooks.engine.PlaybookEngine", return_value=_engine({})):
            result = await tool.safe_execute({"playbook": "x", "target": "t"})
        assert result["isError"] is True
        payload = json.loads(result["content"][0]["text"])
        assert payload["error"] == "Internal error in playbook_run"


# ── _run_background / _truncate_payload already covered above; test _run_background directly


class TestRunBackground:
    async def test_success(self):
        job_id = "job_bg_ok"
        JOB_REGISTRY[job_id] = {"job_id": job_id, "status": "running"}

        async def coro():
            JOB_REGISTRY[job_id]["status"] = "completed"

        from kali_mcp.tools.playbook_blackbox import _run_background

        await _run_background(job_id, coro)
        assert JOB_REGISTRY[job_id]["status"] == "completed"

    async def test_exception_marks_failed(self):
        job_id = "job_bg_fail"
        JOB_REGISTRY[job_id] = {"job_id": job_id, "status": "running"}

        async def coro():
            raise RuntimeError("bg boom")

        from kali_mcp.tools.playbook_blackbox import _run_background

        await _run_background(job_id, coro)
        assert JOB_REGISTRY[job_id]["status"] == "failed"
        assert "bg boom" in JOB_REGISTRY[job_id]["error"]

    async def test_exception_missing_registry_no_crash(self):
        from kali_mcp.tools.playbook_blackbox import _run_background

        async def coro():
            raise RuntimeError("bg boom")

        await _run_background("job_does_not_exist", coro)  # STATUS is None -> skip


# ── PlaybookCatalogTool ───────────────────────────────────────────────


class TestPlaybookCatalogTool:
    def test_properties_schema_validate_command(self):
        tool = PlaybookCatalogTool()
        assert tool.name == "playbook_catalog"
        assert tool.description
        tool.input_schema()
        tool.validate({})  # no-op
        assert tool.build_command({}) == ["playbook_catalog"]

    async def test_execute_compact(self):
        tool = PlaybookCatalogTool()
        playbooks = [
            {
                "id": "pb1",
                "name": "PB1",
                "description": "d1",
                "estimated_duration": 60,
                "inputs": {},
                "outputs": {},
                "execution": {"timeout": 60},
            }
        ]
        with patch(
            "kali_mcp.playbooks.registry.list_playbooks", return_value=playbooks
        ):
            result = await tool.execute({"detail": "compact"})
        assert result["isError"] is False
        payload = _tool_payload(result)
        assert payload["count"] == 1
        assert payload["playbooks"] == [
            {"id": "pb1", "name": "PB1", "description": "d1", "estimated_duration": 60}
        ]

    async def test_execute_full_keeps_full_dicts(self):
        tool = PlaybookCatalogTool()
        playbooks = [
            {"id": "pb1", "name": "PB1", "description": "d1", "inputs": {}, "outputs": {}}
        ]
        with patch(
            "kali_mcp.playbooks.registry.list_playbooks", return_value=playbooks
        ):
            result = await tool.execute({"detail": "full"})
        payload = _tool_payload(result)
        assert payload["playbooks"] == playbooks
        assert payload["count"] == 1


# ── PlaybookResultTool ────────────────────────────────────────────────


class TestPlaybookResultTool:
    def test_properties_validate_command(self):
        tool = PlaybookResultTool()
        assert tool.name == "playbook_result"
        assert tool.description
        tool.input_schema()
        assert tool.build_command({"assessment_id": "a"}) == ["playbook_result", "a"]
        assert tool.build_command({"job_id": "j"}) == ["playbook_result", "j"]
        tool.validate({"job_id": "j"})
        tool.validate({"assessment_id": "a"})

    @pytest.mark.parametrize("args", [{}, {"assessment_id": ""}, {"job_id": ""}])
    def test_validate_missing_identifier(self, args):
        tool = PlaybookResultTool()
        with pytest.raises(ValueError, match="assessment_id or job_id is required"):
            tool.validate(args)

    async def test_execute_registry_running(self):
        tool = PlaybookResultTool()
        job_id = "job_run"
        JOB_REGISTRY[job_id] = {
            "job_id": job_id,
            "assessment_id": "assess_run",
            "playbook": "pb",
            "target": "t",
            "status": "running",
            "started_at": "x",
        }
        result = await tool.execute({"job_id": job_id})
        assert result["isError"] is False
        payload = _tool_payload(result)
        assert payload["status"] == "running"
        assert payload["result"] is None
        assert "error" not in payload
        assert payload["next_actions"][0].startswith("Job still running")

    async def test_execute_registry_completed_with_result(self):
        tool = PlaybookResultTool()
        job_id = "job_done"
        assessment = {"execution": {"status": "completed"}, "assets": {}}
        JOB_REGISTRY[job_id] = {
            "job_id": job_id,
            "assessment_id": "assess_done",
            "playbook": "pb",
            "target": "t",
            "status": "completed",
            "result": assessment,
            "finished_at": "x",
        }
        result = await tool.execute({"assessment_id": "assess_done"})
        payload = _tool_payload(result)
        assert payload["status"] == "completed"
        assert payload["result"] == assessment

    async def test_execute_registry_failed_with_error(self):
        tool = PlaybookResultTool()
        job_id = "job_err"
        JOB_REGISTRY[job_id] = {
            "job_id": job_id,
            "assessment_id": "assess_err",
            "playbook": "pb",
            "target": "t",
            "status": "failed",
            "error": "boom: something",
            "result": {},
        }
        result = await tool.execute({"assessment_id": "assess_err"})
        payload = _tool_payload(result)
        assert payload["status"] == "failed"
        assert payload["error"] == "boom: something"

    async def test_execute_vault_direct_hit_str(self):
        tool = PlaybookResultTool()
        key = "job_unknown"
        data = {"assessment_id": "a", "playbook_id": "pb", "target": "t"}
        with patch(
            "kali_mcp.utils.vault.vault_read", return_value=json.dumps(data)
        ):
            result = await tool.execute({"job_id": key})
        assert result["isError"] is False
        payload = _tool_payload(result)
        assert payload["status"] == "completed"
        assert payload["result"] == data
        assert payload["job_id"] == key

    async def test_execute_vault_direct_hit_dict(self):
        tool = PlaybookResultTool()
        key = "job_unknown"
        data = {"assessment_id": "a", "playbook_id": "pb", "target": "t"}
        with patch("kali_mcp.utils.vault.vault_read", return_value=data):  # not str
            result = await tool.execute({"job_id": key})
        assert result["isError"] is False
        payload = _tool_payload(result)
        assert payload["result"] == data

    async def test_execute_vault_notfound_query_rows(self):
        tool = PlaybookResultTool()
        key = "job_unknown"
        notfound = json.dumps({"error": "not found"})
        rows = [{"category": "playbook_results", "name": "job_cand"}]
        with patch(
            "kali_mcp.utils.vault.vault_read", return_value=notfound
        ), patch(
            "kali_mcp.utils.vault.vault_query", return_value={"rows": rows}
        ):
            result = await tool.execute({"job_id": key})
        payload = _tool_payload(result)
        assert payload["status"] == "found"
        assert payload["candidate_rows"] == rows

    async def test_execute_vault_query_uses_results_key(self):
        tool = PlaybookResultTool()
        key = "job_unknown"
        notfound = json.dumps({"error": "not found"})
        with patch(
            "kali_mcp.utils.vault.vault_read", return_value=notfound
        ), patch(
            "kali_mcp.utils.vault.vault_query",
            return_value={"results": [{"category": "c", "name": "n"}]},
        ):
            result = await tool.execute({"job_id": key})
        payload = _tool_payload(result)
        assert payload["status"] == "found"
        assert len(payload["candidate_rows"]) == 1

    async def test_execute_vault_empty_rows_not_found(self):
        tool = PlaybookResultTool()
        key = "job_unknown"
        notfound = json.dumps({"error": "not found"})
        with patch(
            "kali_mcp.utils.vault.vault_read", return_value=notfound
        ), patch(
            "kali_mcp.utils.vault.vault_query", return_value={"rows": []}
        ):
            result = await tool.execute({"job_id": key})
        assert result["isError"] is True
        payload = json.loads(result["content"][0]["text"])
        assert payload["error"] == "Result not found"

    async def test_execute_vault_read_empty_string_not_found(self):
        tool = PlaybookResultTool()
        key = "job_unknown"
        # raw_text = "" is falsy -> skips direct hit -> vault query -> not found
        with patch(
            "kali_mcp.utils.vault.vault_read", return_value=""
        ), patch(
            "kali_mcp.utils.vault.vault_query", return_value={"rows": []}
        ):
            result = await tool.execute({"job_id": key})
        assert result["isError"] is True
        payload = json.loads(result["content"][0]["text"])
        assert payload["error"] == "Result not found"

    async def test_execute_vault_exception_not_found(self):
        tool = PlaybookResultTool()
        key = "job_unknown"
        with patch(
            "kali_mcp.utils.vault.vault_read", side_effect=OSError("vault down")
        ):
            result = await tool.execute({"job_id": key})
        assert result["isError"] is True
        payload = json.loads(result["content"][0]["text"])
        assert payload["error"] == "Result not found"

    async def test_execute_no_match_anywhere_not_found(self):
        tool = PlaybookResultTool()
        result = await tool.execute({"job_id": "totally_missing_job"})
        assert result["isError"] is True
        payload = json.loads(result["content"][0]["text"])
        assert payload["error"] == "Result not found"
        assert "totally_missing_job" in payload["details"]
