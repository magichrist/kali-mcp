"""Unit tests for tools/playbook_recon.py.

Covers input_schema, validate, build_command, _playbook_definition DAG branches
(skip_nuclei on/off, resume, timeout), and execute (success + validation error).
No real workflow execution — load_playbook/run_playbook_async are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from kali_mcp.tools.playbook_recon import PlaybookReconTool


class _FakeResult:
    """Stand-in for ExecutionResult with a mutable stdout and to_dict()."""

    def __init__(self):
        self.stdout = ""

    def to_dict(self):
        return {"status": "completed", "exit_code": 0}


class TestSchemaAndDefaults:
    def test_name(self):
        assert PlaybookReconTool().name == "playbook_recon"

    def test_description_nonempty(self):
        assert PlaybookReconTool().description.strip()

    def test_default_timeout(self):
        assert PlaybookReconTool().default_timeout == 1800

    def test_input_schema(self):
        schema = PlaybookReconTool().input_schema()
        assert schema["type"] == "object"
        assert set(schema["properties"]) == {
            "target",
            "skip_nuclei",
            "resume",
            "timeout",
        }
        assert schema["required"] == ["target"]
        assert schema["properties"]["target"]["type"] == "string"
        assert schema["properties"]["skip_nuclei"]["type"] == "boolean"
        assert schema["properties"]["skip_nuclei"]["default"] is False
        assert schema["properties"]["resume"]["type"] == "boolean"
        assert schema["properties"]["resume"]["default"] is False
        assert schema["properties"]["timeout"]["type"] == "integer"
        assert schema["properties"]["timeout"]["default"] == 1800


class TestValidate:
    def test_valid_target_passes(self):
        PlaybookReconTool().validate({"target": "example.com"})

    def test_missing_target_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: target"):
            PlaybookReconTool().validate({})

    def test_empty_target_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            PlaybookReconTool().validate({"target": "   "})


class TestBuildCommand:
    def test_with_target(self):
        assert PlaybookReconTool().build_command({"target": "example.com"}) == [
            "playbook_recon",
            "example.com",
        ]

    def test_without_target_defaults_empty(self):
        assert PlaybookReconTool().build_command({}) == ["playbook_recon", ""]


class TestPlaybookDefinition:
    def _step_ids(self, definition):
        return [s["id"] for s in definition["steps"]]

    def _steps_by_id(self, definition):
        return {s["id"]: s for s in definition["steps"]}

    def test_default_includes_vuln_scan(self):
        tool = PlaybookReconTool()
        definition = tool._playbook_definition({"target": "example.com"})
        assert definition["name"] == "playbook_recon"
        assert definition["version"] == "2.0"
        assert definition["inputs"] == {"target": "example.com"}
        assert definition["execution"]["max_parallel"] == 4
        assert definition["execution"]["timeout"] == 1800
        assert definition["execution"]["resume"] is False
        ids = self._step_ids(definition)
        assert "validate" == ids[0]
        assert "vuln_scan" in ids
        assert ids.index("discover") < ids.index("resolve")
        assert ids.index("resolve") < ids.index("technologies")
        assert ids.index("ports") < ids.index("nmap_scan")

    def test_skip_nuclei_excludes_vuln_scan(self):
        tool = PlaybookReconTool()
        definition = tool._playbook_definition({"target": "example.com", "skip_nuclei": True})
        ids = self._step_ids(definition)
        assert "vuln_scan" not in ids

    def test_skip_nuclei_false_includes_vuln_scan(self):
        tool = PlaybookReconTool()
        definition = tool._playbook_definition(
            {"target": "example.com", "skip_nuclei": False}
        )
        ids = self._step_ids(definition)
        assert "vuln_scan" in ids

    def test_resume_and_timeout_honored(self):
        tool = PlaybookReconTool()
        definition = tool._playbook_definition(
            {"target": "example.com", "resume": True, "timeout": 900}
        )
        assert definition["execution"]["resume"] is True
        assert definition["execution"]["timeout"] == 900

    def test_validate_step_is_scope_check(self):
        tool = PlaybookReconTool()
        definition = tool._playbook_definition({"target": "example.com"})
        assert definition["steps"][0]["id"] == "validate"
        assert definition["steps"][0]["type"] == "scope_check"

    def test_report_depends_on_correlate(self):
        tool = PlaybookReconTool()
        definition = tool._playbook_definition({"target": "example.com"})
        steps = self._steps_by_id(definition)
        assert steps["report"]["depends_on"] == ["correlate"]
        assert steps["correlate"]["depends_on"] == ["resolve", "technologies", "nmap_scan"]
        assert steps["nmap_scan"]["tool"] == "nmap"
        assert steps["nmap_scan"]["args"]["scan_type"] == "-sV"
        assert steps["discover"]["tool"] == "subfinder"
        assert steps["resolve"]["tool"] == "httpx"
        assert steps["technologies"]["tool"] == "whatweb"
        assert steps["ports"]["tool"] == "masscan"


class TestExecute:
    async def test_execute_success(self):
        tool = PlaybookReconTool()
        fake_result = _FakeResult()
        with patch(
            "kali_mcp.workflow.load_playbook", return_value={"name": "playbook_recon"}
        ) as mock_load, patch(
            "kali_mcp.workflow.run_playbook_async",
            new=AsyncMock(return_value=fake_result),
        ) as mock_run:
            result = await tool.execute({"target": "example.com"})
        mock_load.assert_called_once()
        mock_run.assert_awaited_once()
        assert mock_run.await_args.kwargs["resume"] is False
        assert result["isError"] is False
        assert "content" in result

    async def test_execute_resume_true(self):
        tool = PlaybookReconTool()
        fake_result = _FakeResult()
        with patch(
            "kali_mcp.workflow.load_playbook", return_value={"name": "pb"}
        ), patch(
            "kali_mcp.workflow.run_playbook_async",
            new=AsyncMock(return_value=fake_result),
        ) as mock_run:
            await tool.execute({"target": "example.com", "resume": True})
        assert mock_run.await_args.kwargs["resume"] is True

    async def test_execute_validation_error_propagates(self):
        tool = PlaybookReconTool()
        with pytest.raises(ValueError, match="Missing required parameter: target"):
            await tool.execute({})
