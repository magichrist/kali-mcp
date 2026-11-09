"""Unit tests for tools/playbook_webapp.py.

Covers input_schema, validate (incl. URL validation), build_command,
_playbook_definition DAG branches (wordlist default/custom, resume, timeout,
parallel flags), and execute (success + validation error). No real workflow
execution — load_playbook/run_playbook_async are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from kali_mcp.tools.playbook_webapp import PlaybookWebappTool


class _FakeResult:
    """Stand-in for ExecutionResult with a mutable stdout and to_dict()."""

    def __init__(self):
        self.stdout = ""

    def to_dict(self):
        return {"status": "completed", "exit_code": 0}


class TestSchemaAndDefaults:
    def test_name(self):
        assert PlaybookWebappTool().name == "playbook_webapp"

    def test_description_nonempty(self):
        assert PlaybookWebappTool().description.strip()

    def test_default_timeout(self):
        assert PlaybookWebappTool().default_timeout == 2400

    def test_input_schema(self):
        schema = PlaybookWebappTool().input_schema()
        assert schema["type"] == "object"
        assert set(schema["properties"]) == {
            "target",
            "wordlist",
            "resume",
            "timeout",
        }
        assert schema["required"] == ["target"]
        assert schema["properties"]["target"]["type"] == "string"
        assert schema["properties"]["wordlist"]["type"] == "string"
        assert schema["properties"]["resume"]["type"] == "boolean"
        assert schema["properties"]["resume"]["default"] is False
        assert schema["properties"]["timeout"]["type"] == "integer"
        assert schema["properties"]["timeout"]["default"] == 2400


class TestValidate:
    def test_valid_url_passes(self):
        PlaybookWebappTool().validate({"target": "http://127.0.0.1"})
        PlaybookWebappTool().validate({"target": "https://example.com"})

    def test_missing_target_raises(self):
        with pytest.raises(ValueError, match="Missing required parameter: target"):
            PlaybookWebappTool().validate({})

    def test_empty_target_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            PlaybookWebappTool().validate({"target": "   "})

    def test_invalid_url_scheme_raises(self):
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            PlaybookWebappTool().validate({"target": "ftp://bad-scheme"})


class TestBuildCommand:
    def test_with_target(self):
        assert PlaybookWebappTool().build_command({"target": "http://x"}) == [
            "playbook_webapp",
            "http://x",
        ]

    def test_without_target_defaults_empty(self):
        assert PlaybookWebappTool().build_command({}) == ["playbook_webapp", ""]


class TestPlaybookDefinition:
    def _step_ids(self, definition):
        return [s["id"] for s in definition["steps"]]

    def _steps_by_id(self, definition):
        return {s["id"]: s for s in definition["steps"]}

    def test_default_wordlist(self):
        tool = PlaybookWebappTool()
        definition = tool._playbook_definition({"target": "http://example.com"})
        ffuf = self._steps_by_id(definition)["ffuf"]
        assert ffuf["args"]["wordlist"] == "/usr/share/wordlists/dirb/common.txt"

    def test_custom_wordlist(self):
        tool = PlaybookWebappTool()
        definition = tool._playbook_definition(
            {"target": "http://example.com", "wordlist": "/tmp/custom.txt"}
        )
        ffuf = self._steps_by_id(definition)["ffuf"]
        assert ffuf["args"]["wordlist"] == "/tmp/custom.txt"

    def test_empty_wordlist_uses_default(self):
        tool = PlaybookWebappTool()
        definition = tool._playbook_definition({"target": "http://example.com", "wordlist": ""})
        ffuf = self._steps_by_id(definition)["ffuf"]
        assert ffuf["args"]["wordlist"] == "/usr/share/wordlists/dirb/common.txt"

    def test_default_execution(self):
        tool = PlaybookWebappTool()
        definition = tool._playbook_definition({"target": "http://example.com"})
        assert definition["name"] == "playbook_webapp"
        assert definition["version"] == "2.0"
        assert definition["inputs"] == {"target": "http://example.com"}
        assert definition["execution"]["max_parallel"] == 4
        assert definition["execution"]["timeout"] == 2400
        assert definition["execution"]["resume"] is False

    def test_resume_and_timeout_honored(self):
        tool = PlaybookWebappTool()
        definition = tool._playbook_definition(
            {"target": "http://example.com", "resume": True, "timeout": 600}
        )
        assert definition["execution"]["resume"] is True
        assert definition["execution"]["timeout"] == 600

    def test_step_structure_and_parallel_flags(self):
        tool = PlaybookWebappTool()
        definition = tool._playbook_definition({"target": "http://example.com"})
        steps = self._steps_by_id(definition)
        ids = self._step_ids(definition)
        assert ids[0] == "validate"
        assert steps["validate"]["type"] == "scope_check"
        assert steps["crawl"]["tool"] == "katana"
        assert steps["params"]["tool"] == "arjun"
        assert steps["ffuf"]["tool"] == "ffuf"
        assert steps["ffuf"]["parallel"] is True
        assert steps["nuclei"]["tool"] == "nuclei"
        assert steps["sqlmap"]["tool"] == "sqlmap"
        assert steps["sqlmap"]["parallel"] is True
        assert steps["commix"]["tool"] == "commix"
        assert steps["commix"]["parallel"] is True
        assert steps["correlate"]["type"] == "finding_correlation"
        assert steps["report"]["type"] == "assessment_report"
        assert steps["report"]["depends_on"] == ["correlate"]
        assert steps["nuclei"]["depends_on"] == ["crawl", "params", "ffuf"]
        assert steps["correlate"]["depends_on"] == ["nuclei", "sqlmap", "commix"]


class TestExecute:
    async def test_execute_success(self):
        tool = PlaybookWebappTool()
        fake_result = _FakeResult()
        with (
            patch(
                "kali_mcp.workflow.load_playbook", return_value={"name": "playbook_webapp"}
            ) as mock_load,
            patch(
                "kali_mcp.workflow.run_playbook_async",
                new=AsyncMock(return_value=fake_result),
            ) as mock_run,
        ):
            result = await tool.execute({"target": "http://example.com"})
        mock_load.assert_called_once()
        mock_run.assert_awaited_once()
        assert mock_run.await_args.kwargs["resume"] is False
        assert result["isError"] is False
        assert "content" in result

    async def test_execute_resume_true(self):
        tool = PlaybookWebappTool()
        fake_result = _FakeResult()
        with (
            patch("kali_mcp.workflow.load_playbook", return_value={"name": "pb"}),
            patch(
                "kali_mcp.workflow.run_playbook_async",
                new=AsyncMock(return_value=fake_result),
            ) as mock_run,
        ):
            await tool.execute({"target": "http://example.com", "resume": True})
        assert mock_run.await_args.kwargs["resume"] is True

    async def test_execute_validation_error_propagates(self):
        tool = PlaybookWebappTool()
        with pytest.raises(ValueError, match="Missing required parameter: target"):
            await tool.execute({})

    async def test_execute_invalid_url_propagates(self):
        tool = PlaybookWebappTool()
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            await tool.execute({"target": "ftp://bad-scheme"})
