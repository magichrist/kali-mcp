"""Unit tests for agent-facing playbook authoring tools (draft → validate → publish).

Covers:
  - tool registration (ALL_TOOLS + registry names)
  - PlaybookCreateTool / PlaybookValidateTool / PlaybookPublishTool contracts
  - DSL guide module + prompt + resource wiring
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from kali_mcp.playbook_dsl import PLAYBOOK_DSL_GUIDE
from kali_mcp.tools import ALL_TOOLS
from kali_mcp.tools.playbook_authoring import (
    PlaybookCreateTool,
    PlaybookPublishTool,
    PlaybookValidateTool,
)

# A minimal valid definition (mirrors the DSL guide's example). ``httpx`` is
# a real server tool so publish-time catalog checks can pass.
VALID_DEFINITION = {
    "name": "quick_http_probe",
    "version": "1.0",
    "inputs": {
        "target": {"type": "string", "required": True, "description": "Host to probe"},
    },
    "execution": {"max_parallel": 4, "timeout": 900, "resume": True},
    "steps": [
        {
            "id": "scope",
            "type": "scope_check",
            "checkpoint": True,
        },
        {
            "id": "httpx",
            "tool": "httpx",
            "depends_on": ["scope"],
            "args": {"target": "{{target}}"},
            "budget": {"timeout": 120},
        },
    ],
}

INVALID_DEFINITION = {
    "name": "bad_pb",
    "steps": [
        {"id": "a", "tool": "httpx", "args": {}},
        {"id": "a", "tool": "nuclei", "args": {}},  # duplicate step id → error
    ],
}


def _parse(response: dict) -> dict:
    """Parse an MCP response body (payload JSON for success, error dict for failure)."""
    body = json.loads(response["content"][0]["text"])
    # Success responses wrap the payload inside ExecutionResult.stdout.
    stdout = body.get("stdout")
    if isinstance(stdout, str):
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(payload, dict) and "success" in body:
                return payload
    return body


# ── registration ──────────────────────────────────────────────────────────


class TestRegistration:
    def test_authoring_tools_registered(self) -> None:
        names = {t.name for t in ALL_TOOLS}
        assert {"playbook_create", "playbook_validate", "playbook_publish"} <= names

    def test_authoring_tools_skip_central_persist(self) -> None:
        assert PlaybookCreateTool._skip_central_persist is True
        assert PlaybookValidateTool._skip_central_persist is True
        assert PlaybookPublishTool._skip_central_persist is True


# ── PlaybookCreateTool ────────────────────────────────────────────────────


class TestPlaybookCreateTool:
    def test_validate_requires_fields(self) -> None:
        tool = PlaybookCreateTool()
        with pytest.raises(ValueError, match="playbook_id"):
            tool.validate({})
        with pytest.raises(ValueError, match="name"):
            tool.validate({"playbook_id": "x"})
        tool.validate({"playbook_id": "x", "name": "X"})
        with pytest.raises(ValueError, match="non-empty"):
            tool.validate({"playbook_id": "  ", "name": "X"})

    def test_build_command(self) -> None:
        assert PlaybookCreateTool().build_command({}) == ["playbook_create"]

    @pytest.mark.asyncio
    async def test_create_success(self) -> None:
        tool = PlaybookCreateTool()
        fake_db = MagicMock()
        row = {"playbook_id": "pb1", "name": "PB 1", "status": "draft"}
        with (
            patch(
                "kali_mcp.tools.playbook_authoring.db_manager.get_db", return_value=fake_db
            ),
            patch("kali_mcp.studio.playbook_service.get_playbook", return_value=None),
            patch(
                "kali_mcp.studio.playbook_service.create_playbook", return_value=row
            ) as create,
        ):
            response = await tool.execute(
                {"playbook_id": "pb1", "name": "PB 1", "category": "recon"}
            )
        body = _parse(response)
        assert response["isError"] is False
        assert body["created"] is True
        assert body["status"] == "draft"
        create.assert_called_once()
        # author defaults to 'agent'
        assert create.call_args.kwargs.get("author") == "agent"

    @pytest.mark.asyncio
    async def test_create_rejects_existing(self) -> None:
        tool = PlaybookCreateTool()
        fake_db = MagicMock()
        with (
            patch(
                "kali_mcp.tools.playbook_authoring.db_manager.get_db", return_value=fake_db
            ),
            patch(
                "kali_mcp.studio.playbook_service.get_playbook",
                return_value={"playbook_id": "pb1", "status": "published"},
            ),
        ):
            response = await tool.execute({"playbook_id": "pb1", "name": "PB 1"})
        assert response["isError"] is True
        body = _parse(response)
        assert "already exists" in body["error"]

    @pytest.mark.asyncio
    async def test_create_db_unavailable(self) -> None:
        tool = PlaybookCreateTool()
        with patch("kali_mcp.tools.playbook_authoring.db_manager.get_db", return_value=None):
            response = await tool.execute({"playbook_id": "pb1", "name": "PB 1"})
        assert response["isError"] is True
        assert "database unavailable" in _parse(response)["error"]

    @pytest.mark.asyncio
    async def test_create_wraps_value_error(self) -> None:
        tool = PlaybookCreateTool()
        fake_db = MagicMock()
        with (
            patch(
                "kali_mcp.tools.playbook_authoring.db_manager.get_db", return_value=fake_db
            ),
            patch("kali_mcp.studio.playbook_service.get_playbook", return_value=None),
            patch(
                "kali_mcp.studio.playbook_service.create_playbook",
                side_effect=ValueError("boom"),
            ),
        ):
            response = await tool.execute({"playbook_id": "pb1", "name": "PB 1"})
        assert response["isError"] is True
        assert "boom" in _parse(response)["error"]


# ── PlaybookValidateTool ──────────────────────────────────────────────────


class TestPlaybookValidateTool:
    def test_validate_requires_definition(self) -> None:
        tool = PlaybookValidateTool()
        with pytest.raises(ValueError, match="definition"):
            tool.validate({"playbook_id": "x"})
        with pytest.raises(ValueError, match="playbook_id"):
            tool.validate({"definition": {}})

    @pytest.mark.asyncio
    async def test_validate_valid_definition(self) -> None:
        tool = PlaybookValidateTool()
        validation = {"valid": True, "findings": []}
        with patch(
            "kali_mcp.tools.playbook_authoring._validate_definition",
            return_value=validation,
        ) as vd:
            response = await tool.execute(
                {"playbook_id": "pb1", "definition": dict(VALID_DEFINITION)}
            )
        body = _parse(response)
        assert body["valid"] is True
        assert body["findings"] == []
        assert body["for_publish"] is True  # default
        assert vd.call_args.kwargs["for_publish"] is True

    @pytest.mark.asyncio
    async def test_validate_invalid_definition_reports_findings(self) -> None:
        tool = PlaybookValidateTool()
        findings = [
            {"severity": "error", "step_id": "a", "field": "id", "message": "duplicate step id"},
        ]
        validation = {"valid": False, "findings": findings}
        with patch(
            "kali_mcp.tools.playbook_authoring._validate_definition", return_value=validation
        ):
            response = await tool.execute(
                {"playbook_id": "pb1", "definition": dict(INVALID_DEFINITION)}
            )
        body = _parse(response)
        assert body["valid"] is False
        assert body["readable"].startswith("[error] a:id")
        assert "fix every severity=error finding" in body["next"]

    @pytest.mark.asyncio
    async def test_validate_accepts_yaml_string(self) -> None:
        tool = PlaybookValidateTool()
        validation = {"valid": True, "findings": []}
        with patch(
            "kali_mcp.tools.playbook_authoring._validate_definition", return_value=validation
        ) as vd:
            response = await tool.execute(
                {"playbook_id": "pb1", "definition": json.dumps(VALID_DEFINITION)}
            )
        assert _parse(response)["valid"] is True
        passed = vd.call_args.args[1]
        assert passed["name"] == "quick_http_probe"


# ── PlaybookPublishTool ───────────────────────────────────────────────────


class TestPlaybookPublishTool:
    def test_validate_requires_fields(self) -> None:
        tool = PlaybookPublishTool()
        with pytest.raises(ValueError, match="playbook_id"):
            tool.validate({})
        with pytest.raises(ValueError, match="version"):
            tool.validate({"playbook_id": "x", "definition": {}})
        with pytest.raises(ValueError, match="definition"):
            tool.validate({"playbook_id": "x", "version": "1.0"})
        tool.validate({"playbook_id": "x", "version": "1.0", "definition": {}})

    @pytest.mark.asyncio
    async def test_publish_requires_existing_playbook(self) -> None:
        tool = PlaybookPublishTool()
        fake_db = MagicMock()
        with (
            patch("kali_mcp.tools.playbook_authoring.db_manager.get_db", return_value=fake_db),
            patch("kali_mcp.studio.playbook_service.get_playbook", return_value=None),
        ):
            response = await tool.execute(
                {"playbook_id": "pb1", "version": "1.0", "definition": VALID_DEFINITION}
            )
        body = _parse(response)
        assert response["isError"] is True
        assert "does not exist" in body["error"]
        assert "playbook_create" in body["details"]

    @pytest.mark.asyncio
    async def test_publish_blocks_invalid_definition(self) -> None:
        tool = PlaybookPublishTool()
        fake_db = MagicMock()
        findings = [{"severity": "error", "step_id": None, "field": "definition", "message": "bad"}]
        with (
            patch("kali_mcp.tools.playbook_authoring.db_manager.get_db", return_value=fake_db),
            patch(
                "kali_mcp.studio.playbook_service.get_playbook",
                return_value={"playbook_id": "pb1"},
            ),
            patch(
                "kali_mcp.studio.playbook_service.validate_definition",
                return_value={"valid": False, "findings": findings},
            ),
            patch("kali_mcp.studio.playbook_service.publish_version"),  # must not be called
        ):
            response = await tool.execute(
                {"playbook_id": "pb1", "version": "1.0", "definition": VALID_DEFINITION}
            )
        body = _parse(response)
        assert response["isError"] is False
        assert body["published"] is False
        assert body["valid"] is False

    @pytest.mark.asyncio
    async def test_publish_success(self) -> None:
        tool = PlaybookPublishTool()
        fake_db = MagicMock()
        with (
            patch("kali_mcp.tools.playbook_authoring.db_manager.get_db", return_value=fake_db),
            patch(
                "kali_mcp.studio.playbook_service.get_playbook",
                return_value={"playbook_id": "pb1"},
            ),
            patch(
                "kali_mcp.studio.playbook_service.validate_definition",
                return_value={"valid": True, "findings": []},
            ),
            patch(
                "kali_mcp.studio.playbook_service.publish_version", return_value=42
            ) as publish,
        ):
            response = await tool.execute(
                {
                    "playbook_id": "pb1",
                    "version": "1.0",
                    "definition": VALID_DEFINITION,
                    "notes": "first version",
                }
            )
        body = _parse(response)
        assert body["published"] is True
        assert body["version_id"] == 42
        publish.assert_called_once()
        assert publish.call_args.kwargs["published_by"] == "agent"
        assert publish.call_args.kwargs["notes"] == "first version"


# ── DSL guide + prompt + resource wiring ──────────────────────────────────


class TestDslGuideWiring:
    def test_guide_covers_core_grammar(self) -> None:
        for token in (
            "## Step types",
            "## Substitution and references",
            "## Step fields reference",
            "## ``when`` conditions",
            "## foreach (fan-out)",
            "playbook_publish",
        ):
            assert token in PLAYBOOK_DSL_GUIDE

    def test_resource_reader_returns_guide(self) -> None:
        from kali_mcp.resources import _playbook_dsl_resource

        assert _playbook_dsl_resource() == PLAYBOOK_DSL_GUIDE

    def test_resource_registered(self) -> None:
        from unittest.mock import MagicMock

        from kali_mcp.resources import register_resources

        fake_mcp = MagicMock()
        register_resources(fake_mcp)
        uris = [call.args[0] for call in fake_mcp.resource.call_args_list]
        assert "kali://playbook/dsl" in uris

    def test_prompt_registered(self) -> None:
        from kali_mcp.prompts import register_prompts

        fake_mcp = MagicMock()
        register_prompts(fake_mcp)
        names = [call.kwargs.get("name") for call in fake_mcp.prompt.call_args_list]
        assert "playbook_authoring" in names
        assert fake_mcp.prompt.call_count == 7
