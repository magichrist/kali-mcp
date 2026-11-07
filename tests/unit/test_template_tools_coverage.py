"""Coverage-focused unit tests for ``src/kali_mcp/tools/template_tools.py``.

Covers:
  - template_list and template_run tool schema, validate, execute
  - template render branches (TemplateNotFound, PlaybookError, success)
  - parameter substitution, default merging, password redaction in background
  - foreground engine success and exception paths
  - _run_background, _guarded, _payload_from_execution
  - error paths: missing template_id, bad params, unknown template, not found
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kali_mcp.playbooks.registry import TemplateNotFound
from kali_mcp.workflow.yaml_loader import PlaybookError
from kali_mcp.tools.template_tools import (
    JOB_REGISTRY,
    TemplateListTool,
    TemplateRunTool,
    _new_id,
    _success_tool_result,
)


@pytest.fixture(autouse=True)
def _clear_job_registry():
    JOB_REGISTRY.clear()
    yield
    JOB_REGISTRY.clear()


class _FakeResult:
    """Stand-in for the workflow engine's ExecutionResult."""

    def __init__(self, success: bool, stdout: Any):
        self.success = success
        self.stdout = stdout


def _tool_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Unwrap an MCP tool result into the tool payload dict."""
    return json.loads(json.loads(result["content"][0]["text"])["stdout"])


def test_new_id_shape():
    jid = _new_id("job")
    assert jid.startswith("job_") and len(jid) == len("job_") + 12


def test_success_tool_result():
    res = _success_tool_result("template_run", {"a": 1})
    assert res["isError"] is False
    payload = json.loads(res["content"][0]["text"])
    assert payload["success"] is True
    assert payload["tool"] == "template_run"
    assert json.loads(payload["stdout"]) == {"a": 1}


# ── TemplateListTool ──────────────────────────────────────────────────


class TestTemplateListTool:
    def test_properties_schema_validate_command(self):
        tool = TemplateListTool()
        assert tool.name == "template_list"
        assert tool.description
        tool.validate({})  # no-op
        assert tool.build_command({}) == ["template_list"]

    def test_input_schema(self):
        tool = TemplateListTool()
        schema = tool.input_schema()
        assert schema["type"] == "object"

    async def test_execute_compact(self):
        tool = TemplateListTool()
        templates = [
            {
                "id": "t1",
                "name": "T1",
                "description": "d1",
                "parameters": {
                    "target": {"required": True},
                    "depth": {"required": False},
                },
            }
        ]
        with patch(
            "kali_mcp.playbooks.registry.list_templates", return_value=templates
        ):
            result = await tool.execute({"detail": "compact"})
        assert result["isError"] is False
        payload = _tool_payload(result)
        assert payload["count"] == 1
        assert payload["templates"] == [
            {
                "id": "t1",
                "name": "T1",
                "description": "d1",
                "required_params": ["target"],
            }
        ]
        assert "next_actions" in payload

    async def test_execute_full_keeps_full_dicts(self):
        tool = TemplateListTool()
        templates = [
            {"id": "t1", "name": "T1", "description": "d1", "parameters": {}}
        ]
        with patch(
            "kali_mcp.playbooks.registry.list_templates", return_value=templates
        ):
            result = await tool.execute({"detail": "full"})
        payload = _tool_payload(result)
        assert payload["templates"] == templates
        assert payload["count"] == 1


# ── TemplateRunTool ───────────────────────────────────────────────────


class TestTemplateRunTool:
    def test_properties_schema_command(self):
        tool = TemplateRunTool()
        assert tool.name == "template_run"
        assert tool.description
        assert tool.default_timeout == 3600
        schema = tool.input_schema()
        assert schema["type"] == "object"
        # Both template_id and template are valid; neither is strictly required
        # at the schema level (validate() enforces presence).
        assert set(schema["required"]) == set()
        assert "template_id" in schema["properties"]
        assert "template" in schema["properties"]
        assert tool.build_command({"template_id": "t1"}) == ["template_run", "t1"]
        assert tool.build_command({"template": "t1"}) == ["template_run", "t1"]

    @pytest.mark.parametrize(
        "args,err",
        [
            ({}, "template_id is required"),
            ({"template_id": "t", "params": "notadict"}, "params must be an object"),
        ],
    )
    def test_validate_rejects(self, args, err):
        tool = TemplateRunTool()
        with pytest.raises(ValueError, match=err):
            tool.validate(args)

    def test_validate_unknown_template(self):
        tool = TemplateRunTool()
        with patch(
            "kali_mcp.playbooks.registry.get_template", side_effect=KeyError("nope")
        ):
            with pytest.raises(ValueError, match="unknown template"):
                tool.validate({"template_id": "nope", "params": {}})

    def test_validate_known_template(self):
        tool = TemplateRunTool()
        with patch(
            "kali_mcp.playbooks.registry.get_template", return_value={"id": "t"}
        ):
            tool.validate({"template_id": "t", "params": {}})

    async def test_execute_render_template_not_found_propagates(self):
        tool = TemplateRunTool()
        with patch(
            "kali_mcp.playbooks.registry.render_template",
            side_effect=TemplateNotFound("missing"),
        ):
            with pytest.raises(TemplateNotFound):
                await tool.execute({"template_id": "missing", "params": {}})

    async def test_execute_render_playbook_error_becomes_value_error(self):
        tool = TemplateRunTool()
        with patch(
            "kali_mcp.playbooks.registry.render_template",
            side_effect=PlaybookError("bad playbook"),
        ):
            with pytest.raises(ValueError, match="template produced an invalid playbook"):
                await tool.execute({"template_id": "t", "params": {}})

    async def test_execute_background_accepted(self):
        tool = TemplateRunTool()
        definition = MagicMock()
        stdout = json.dumps({"steps": [], "step_results": {}})
        with patch(
            "kali_mcp.playbooks.registry.render_template", return_value=definition
        ), patch(
            "kali_mcp.workflow.PlaybookEngine",
            return_value=MagicMock(run=AsyncMock(return_value=_FakeResult(True, stdout))),
        ):
            result = await tool.execute(
                {
                    "template_id": "t",
                    "params": {"target": "x", "password": "secret"},
                    "background": True,
                }
            )
            await asyncio.sleep(0)

        assert result["isError"] is False
        payload = result["template_run"]
        assert payload["status"] == "accepted"
        assert payload["template_id"] == "t"
        # password keys are redacted from the returned params
        assert payload["params"] == {"target": "x"}
        assert result["template_run"] is payload

        assert len(JOB_REGISTRY) == 1
        assert next(iter(JOB_REGISTRY.values()))["status"] == "completed"

    async def test_execute_foreground_success(self):
        tool = TemplateRunTool()
        definition = MagicMock()
        stdout = json.dumps(
            {
                "steps": ["s1"],
                "step_results": {
                    "s1": {"findings": [{"severity": "high"}, {"severity": "low"}]},
                    "s2": "not-a-dict",
                },
            }
        )
        with patch(
            "kali_mcp.playbooks.registry.render_template", return_value=definition
        ), patch(
            "kali_mcp.workflow.PlaybookEngine",
            return_value=MagicMock(run=AsyncMock(return_value=_FakeResult(True, stdout))),
        ):
            result = await tool.execute({"template_id": "t", "params": {"target": "x"}})

        assert result["isError"] is False
        tr = result["template_run"]
        assert tr["status"] == "completed"
        assert tr["steps"] == ["s1"]
        assert tr["findings"] == [{"severity": "high"}, {"severity": "low"}]
        assert tr["summary"] == {"total": 2, "by_severity": {"high": 1, "low": 1}}
        assert tr["template_id"] == "t"
        assert result["template_run"] is tr

    async def test_execute_foreground_engine_exception_marks_failed(self):
        tool = TemplateRunTool()
        definition = MagicMock()
        with patch(
            "kali_mcp.playbooks.registry.render_template", return_value=definition
        ), patch(
            "kali_mcp.workflow.PlaybookEngine",
            return_value=MagicMock(run=AsyncMock(side_effect=RuntimeError("engine boom"))),
        ):
            with pytest.raises(RuntimeError, match="engine boom"):
                await tool.execute({"template_id": "t", "params": {}})

        assert len(JOB_REGISTRY) == 1
        entry = next(iter(JOB_REGISTRY.values()))
        assert entry["status"] == "failed"
        assert "engine boom" in entry["error"]

    async def test_safe_execute_success(self):
        tool = TemplateRunTool()
        tool._skip_central_persist = True
        definition = MagicMock()
        stdout = json.dumps({"steps": [], "step_results": {}})
        with patch(
            "kali_mcp.playbooks.registry.render_template", return_value=definition
        ), patch(
            "kali_mcp.workflow.PlaybookEngine",
            return_value=MagicMock(run=AsyncMock(return_value=_FakeResult(True, stdout))),
        ):
            result = await tool.safe_execute({"template_id": "t", "params": {}})
        assert result["isError"] is False

    async def test_safe_execute_catches_render_value_error(self):
        tool = TemplateRunTool()
        tool._skip_central_persist = True
        with patch(
            "kali_mcp.playbooks.registry.render_template",
            side_effect=ValueError("render boom"),
        ):
            result = await tool.safe_execute({"template_id": "t", "params": {}})
        assert result["isError"] is True
        payload = json.loads(result["content"][0]["text"])
        assert payload["error"] == "Internal error in template_run"


# ── _run_background ───────────────────────────────────────────────────


class TestRunBackground:
    async def test_password_redaction_and_accepted(self):
        tool = TemplateRunTool()
        definition = MagicMock()
        stdout = json.dumps({"steps": [], "step_results": {}})
        with patch(
            "kali_mcp.workflow.PlaybookEngine",
            return_value=MagicMock(run=AsyncMock(return_value=_FakeResult(True, stdout))),
        ):
            result = await tool._run_background(
                "tpl", definition, {"target": "x", "api_password": "pw", "depth": 1}
            )
            await asyncio.sleep(0)
        assert result["isError"] is False
        payload = _tool_payload(result)
        assert payload["status"] == "accepted"
        assert payload["template_id"] == "tpl"
        assert payload["params"] == {"target": "x", "depth": 1}  # password redacted

        assert len(JOB_REGISTRY) == 1
        assert next(iter(JOB_REGISTRY.values()))["status"] == "completed"

    async def test_background_engine_failure_marks_failed(self):
        tool = TemplateRunTool()
        definition = MagicMock()
        with patch(
            "kali_mcp.workflow.PlaybookEngine",
            return_value=MagicMock(run=AsyncMock(side_effect=RuntimeError("bg boom"))),
        ):
            result = await tool._run_background("tpl", definition, {})
            await asyncio.sleep(0)
        assert result["isError"] is False  # _run_background itself accepts
        assert len(JOB_REGISTRY) == 1
        entry = next(iter(JOB_REGISTRY.values()))
        assert entry["status"] == "failed"
        assert "bg boom" in entry["error"]


# ── _guarded ──────────────────────────────────────────────────────────


class TestGuarded:
    async def test_success_no_failure_recorded(self):
        tool = TemplateRunTool()

        async def run():
            return None

        await tool._guarded("job_g", run)
        assert JOB_REGISTRY.get("job_g") is None

    async def test_exception_marks_failed(self):
        tool = TemplateRunTool()

        async def run():
            raise ValueError("guarded boom")

        await tool._guarded("job_g", run)
        assert JOB_REGISTRY["job_g"]["status"] == "failed"
        assert "guarded boom" in JOB_REGISTRY["job_g"]["error"]


# ── _payload_from_execution ───────────────────────────────────────────


class TestPayloadFromExecution:
    def test_json_stdout_collects_findings(self):
        result = _FakeResult(
            True,
            json.dumps(
                {
                    "steps": ["s1"],
                    "step_results": {
                        "s1": {"findings": [{"severity": "high"}, {"severity": "high"}]},
                        "s2": {"findings": [{"severity": "low"}]},
                    },
                }
            ),
        )
        payload = TemplateRunTool._payload_from_execution("tpl", "job1", result)
        assert payload["job_id"] == "job1"
        assert payload["template_id"] == "tpl"
        assert payload["status"] == "completed"
        assert payload["steps"] == ["s1"]
        assert len(payload["findings"]) == 3
        assert payload["summary"] == {"total": 3, "by_severity": {"high": 2, "low": 1}}

    def test_finding_without_severity_defaults(self):
        result = _FakeResult(
            True,
            json.dumps(
                {"step_results": {"s1": {"findings": [{}, {"severity": "crit"}]}}}
            ),
        )
        payload = TemplateRunTool._payload_from_execution("tpl", "job1", result)
        assert payload["summary"]["by_severity"] == {
            "informational": 1,
            "crit": 1,
        }

    def test_invalid_json_stdout(self):
        result = _FakeResult(False, "not json {")
        payload = TemplateRunTool._payload_from_execution("tpl", "job1", result)
        assert payload["status"] == "failed"
        assert payload["step_results"] == {}
        assert payload["findings"] == []
        assert payload["summary"] == {"total": 0, "by_severity": {}}

    def test_none_and_nonstring_stdout(self):
        for stdout in (None, 123, ["not", "a", "string"]):
            result = _FakeResult(True, stdout)
            payload = TemplateRunTool._payload_from_execution("tpl", "job1", result)
            assert payload["step_results"] == {}
            assert payload["status"] == "completed"

    def test_non_dict_step_result_skipped(self):
        result = _FakeResult(
            True,
            json.dumps({"step_results": {"s1": "just a string", "s2": 42}}),
        )
        payload = TemplateRunTool._payload_from_execution("tpl", "job1", result)
        assert payload["step_results"] == {"s1": "just a string", "s2": 42}
        assert payload["findings"] == []
