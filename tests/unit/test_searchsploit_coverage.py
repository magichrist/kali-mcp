"""Coverage-focused tests for ``kmcp.tools.searchsploit`` (SearchsploitTool).

Covers schema, validate, build_command (title/exact/json/exclude/cve/edb_id/query/
extra_args branches), execute success and both error paths, using mocking to avoid
real subprocesses/network.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from kmcp.models import ExecutionResult
from kmcp.tools.searchsploit import SearchsploitTool

COMMAND = "searchsploit apache"


def _result(stdout='{"ok": true}', exit_code=0):
    return ExecutionResult(
        tool="searchsploit",
        command=COMMAND,
        stdout=stdout,
        stderr="",
        exit_code=exit_code,
        success=exit_code == 0,
        timed_out=False,
        duration=0.1,
        start_time="2026-01-01T00:00:00+00:00",
        end_time="2026-01-01T00:00:01+00:00",
    )


class TestSchemaAndMetadata:
    def test_name_description_default_timeout(self) -> None:
        tool = SearchsploitTool()
        assert tool.name == "searchsploit"
        assert "Exploit-DB" in tool.description
        assert tool.default_timeout == 60

    def test_input_schema_shape(self) -> None:
        tool = SearchsploitTool()
        schema = tool.input_schema()
        assert schema["type"] == "object"
        props = schema["properties"]
        assert "query" in props
        assert schema["required"] == []
        for prop in props.values():
            assert "type" in prop
            assert prop["type"] in ("string", "boolean", "integer")


class TestValidate:
    def test_validate_passes_without_timeout(self) -> None:
        SearchsploitTool().validate({"query": "apache"})
        SearchsploitTool().validate({})

    def test_validate_passes_with_valid_timeout(self) -> None:
        SearchsploitTool().validate({"query": "apache", "timeout": 30})
        SearchsploitTool().validate({"timeout": "60"})

    def test_validate_rejects_invalid_timeout(self) -> None:
        tool = SearchsploitTool()
        with pytest.raises(ValueError):
            tool.validate({"timeout": 0})
        with pytest.raises(ValueError):
            tool.validate({"timeout": -1})
        with pytest.raises(ValueError):
            tool.validate({"timeout": 9999})


class TestBuildCommand:
    def test_binary_only(self) -> None:
        cmd = SearchsploitTool().build_command({})
        assert cmd == ["searchsploit"]

    def test_title_flag(self) -> None:
        cmd = SearchsploitTool().build_command({"title": True})
        assert cmd == ["searchsploit", "-t"]

    def test_exact_flag(self) -> None:
        cmd = SearchsploitTool().build_command({"exact": True})
        assert cmd == ["searchsploit", "-t", "-e"]

    def test_json_flag(self) -> None:
        cmd = SearchsploitTool().build_command({"json": True})
        assert cmd == ["searchsploit", "-j"]

    def test_exclude(self) -> None:
        cmd = SearchsploitTool().build_command({"exclude": "(PoC)|/dos/"})
        assert cmd == ["searchsploit", "--exclude", "(PoC)|/dos/"]

    def test_cve(self) -> None:
        cmd = SearchsploitTool().build_command({"cve": " 2021-44228 "})
        assert cmd == ["searchsploit", "--cve", "2021-44228"]

    def test_cve_blank_skipped(self) -> None:
        cmd = SearchsploitTool().build_command({"cve": "   "})
        assert cmd == ["searchsploit"]

    def test_edb_id(self) -> None:
        cmd = SearchsploitTool().build_command({"edb_id": " 39446 "})
        assert cmd == ["searchsploit", "-p", "39446"]

    def test_edb_id_blank_skipped(self) -> None:
        cmd = SearchsploitTool().build_command({"edb_id": "   "})
        assert cmd == ["searchsploit"]

    def test_query_split_via_shlex(self) -> None:
        cmd = SearchsploitTool().build_command({"query": "apache struts 2.0.0"})
        assert cmd == ["searchsploit", "apache", "struts", "2.0.0"]

    def test_query_blank_skipped(self) -> None:
        cmd = SearchsploitTool().build_command({"query": "   "})
        assert cmd == ["searchsploit"]

    def test_extra_args_split(self) -> None:
        cmd = SearchsploitTool().build_command({"extra_args": "--foo bar"})
        assert "--foo" in cmd and "bar" in cmd

    def test_all_flags_combined(self) -> None:
        cmd = SearchsploitTool().build_command(
            {
                "title": True,
                "exact": True,
                "json": True,
                "exclude": "(PoC)",
                "cve": "2021-44228",
                "edb_id": "39446",
                "query": "apache",
                "extra_args": "--foo",
            }
        )
        assert "-t" in cmd and "-e" in cmd and "-j" in cmd
        assert "--exclude" in cmd and "(PoC)" in cmd
        assert "--cve" in cmd and "2021-44228" in cmd
        assert "-p" in cmd and "39446" in cmd
        assert "apache" in cmd
        assert "--foo" in cmd


class TestExecute:
    async def test_execute_success(self) -> None:
        tool = SearchsploitTool()
        with patch(
            "kmcp.tools.searchsploit.engine.execute", new=AsyncMock(return_value=_result())
        ) as m:
            result = await tool.execute({"query": "apache"})
            assert result["isError"] is False
            assert "content" in result
            m.assert_awaited_once()
            args = m.await_args.args
            assert args[0] == ["searchsploit", "apache"]
            assert m.await_args.kwargs["timeout"] == 60  # timeout == default_timeout

    async def test_execute_uses_provided_timeout(self) -> None:
        tool = SearchsploitTool()
        with patch(
            "kmcp.tools.searchsploit.engine.execute", new=AsyncMock(return_value=_result())
        ) as m:
            await tool.execute({"query": "apache", "timeout": 120})
            assert m.await_args.kwargs["timeout"] == 120

    async def test_execute_validation_error_path(self) -> None:
        tool = SearchsploitTool()
        result = await tool.execute({"timeout": 0})  # validate_timeout raises ValueError
        assert result["isError"] is True
        assert "Validation error" in result["content"][0]["text"]

    async def test_execute_generic_exception_path(self) -> None:
        tool = SearchsploitTool()
        with patch.object(tool, "validate", side_effect=RuntimeError("boom")):
            result = await tool.execute({"query": "apache"})
            assert result["isError"] is True
            assert "Execution failed" in result["content"][0]["text"]
