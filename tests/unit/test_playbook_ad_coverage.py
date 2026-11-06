"""Unit tests for tools/playbook_ad.py.

Covers input_schema, validate, build_command, _playbook_definition DAG branches
(domain default/custom, resume, timeout, parallel flags), and execute (success
+ validation error). No real workflow execution — load_playbook/run_playbook_async
are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from kali_mcp.tools.playbook_ad import PlaybookAdTool


class _FakeResult:
    """Stand-in for ExecutionResult with a mutable stdout and to_dict()."""

    def __init__(self):
        self.stdout = ""

    def to_dict(self):
        return {"status": "completed", "exit_code": 0}


class TestSchemaAndDefaults:
    def test_name(self):
        assert PlaybookAdTool().name == "playbook_ad"

    def test_description_nonempty(self):
        assert PlaybookAdTool().description.strip()

    def test_default_timeout(self):
        assert PlaybookAdTool().default_timeout == 1800

    def test_input_schema(self):
        schema = PlaybookAdTool().input_schema()
        assert schema["type"] == "object"
        assert set(schema["properties"]) == {
            "target",
            "domain",
            "resume",
            "timeout",
        }
        assert schema["required"] == ["target"]
        assert schema["properties"]["target"]["type"] == "string"
        assert schema["properties"]["domain"]["type"] == "string"
        assert schema["properties"]["resume"]["type"] == "boolean"
        assert schema["properties"]["resume"]["default"] is False
        assert schema["properties"]["timeout"]["type"] == "integer"
        assert schema["properties"]["timeout"]["default"] == 1800


class TestValidate:
    def test_valid_target_passes(self):
        PlaybookAdTool().validate({"target": "127.0.0.1"})

    def test_missing_target_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: target"):
            PlaybookAdTool().validate({})

    def test_empty_target_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            PlaybookAdTool().validate({"target": "   "})


class TestBuildCommand:
    def test_with_target(self):
        assert PlaybookAdTool().build_command({"target": "127.0.0.1"}) == [
            "playbook_ad",
            "127.0.0.1",
        ]

    def test_without_target_defaults_empty(self):
        assert PlaybookAdTool().build_command({}) == ["playbook_ad", ""]


class TestPlaybookDefinition:
    def _step_ids(self, definition):
        return [s["id"] for s in definition["steps"]]

    def _steps_by_id(self, definition):
        return {s["id"]: s for s in definition["steps"]}

    def test_domain_defaults_to_target(self):
        tool = PlaybookAdTool()
        definition = tool._playbook_definition({"target": "dc.corp.local"})
        bloodhound = self._steps_by_id(definition)["bloodhound"]
        assert bloodhound["args"]["domain"] == "dc.corp.local"

    def test_custom_domain(self):
        tool = PlaybookAdTool()
        definition = tool._playbook_definition(
            {"target": "127.0.0.1", "domain": "corp.local"}
        )
        bloodhound = self._steps_by_id(definition)["bloodhound"]
        assert bloodhound["args"]["domain"] == "corp.local"

    def test_empty_domain_uses_target(self):
        tool = PlaybookAdTool()
        definition = tool._playbook_definition(
            {"target": "127.0.0.1", "domain": ""}
        )
        bloodhound = self._steps_by_id(definition)["bloodhound"]
        assert bloodhound["args"]["domain"] == "127.0.0.1"

    def test_default_execution(self):
        tool = PlaybookAdTool()
        definition = tool._playbook_definition({"target": "127.0.0.1"})
        assert definition["name"] == "playbook_ad"
        assert definition["version"] == "2.0"
        assert definition["inputs"] == {"target": "127.0.0.1"}
        assert definition["execution"]["max_parallel"] == 4
        assert definition["execution"]["timeout"] == 1800
        assert definition["execution"]["resume"] is False

    def test_resume_and_timeout_honored(self):
        tool = PlaybookAdTool()
        definition = tool._playbook_definition(
            {"target": "127.0.0.1", "resume": True, "timeout": 1200}
        )
        assert definition["execution"]["resume"] is True
        assert definition["execution"]["timeout"] == 1200

    def test_step_structure_and_parallel_flags(self):
        tool = PlaybookAdTool()
        definition = tool._playbook_definition({"target": "127.0.0.1", "domain": "corp.local"})
        steps = self._steps_by_id(definition)
        ids = self._step_ids(definition)
        assert ids[0] == "validate"
        assert steps["validate"]["type"] == "scope_check"
        assert steps["enum4linux"]["tool"] == "enum4linux"
        assert steps["bloodhound"]["tool"] == "bloodhound"
        assert steps["bloodhound"]["depends_on"] == ["enum4linux"]
        assert steps["netexec"]["tool"] == "netexec"
        assert steps["netexec"]["parallel"] is True
        assert steps["netexec"]["args"]["protocol"] == "smb"
        assert steps["crackmapexec"]["tool"] == "crackmapexec"
        assert steps["crackmapexec"]["parallel"] is True
        assert steps["crackmapexec"]["args"]["protocol"] == "smb"
        assert steps["correlate"]["type"] == "finding_correlation"
        assert steps["report"]["type"] == "assessment_report"
        assert steps["report"]["depends_on"] == ["correlate"]
        assert steps["netexec"]["depends_on"] == ["bloodhound"]
        assert steps["crackmapexec"]["depends_on"] == ["bloodhound"]
        assert steps["correlate"]["depends_on"] == ["netexec", "crackmapexec"]


class TestExecute:
    async def test_execute_success(self):
        tool = PlaybookAdTool()
        fake_result = _FakeResult()
        with patch(
            "kali_mcp.workflow.load_playbook", return_value={"name": "playbook_ad"}
        ) as mock_load, patch(
            "kali_mcp.workflow.run_playbook_async",
            new=AsyncMock(return_value=fake_result),
        ) as mock_run:
            result = await tool.execute({"target": "127.0.0.1"})
        mock_load.assert_called_once()
        mock_run.assert_awaited_once()
        assert mock_run.await_args.kwargs["resume"] is False
        assert result["isError"] is False
        assert "content" in result

    async def test_execute_resume_true(self):
        tool = PlaybookAdTool()
        fake_result = _FakeResult()
        with patch(
            "kali_mcp.workflow.load_playbook", return_value={"name": "pb"}
        ), patch(
            "kali_mcp.workflow.run_playbook_async",
            new=AsyncMock(return_value=fake_result),
        ) as mock_run:
            await tool.execute({"target": "127.0.0.1", "resume": True})
        assert mock_run.await_args.kwargs["resume"] is True

    async def test_execute_validation_error_propagates(self):
        tool = PlaybookAdTool()
        with pytest.raises(ValueError, match="Missing required parameter: target"):
            await tool.execute({})
