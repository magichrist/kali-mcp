"""Unit tests for studio/service_mcp_connections.py (Phase 3 Task E).

Covers add_connection, discover_and_import, and test_connection including all
error paths. No real subprocesses or network — MCP client interactions are
mocked with unittest.mock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from kali_mcp.studio import service_mcp_connections as smc
from kali_mcp.studio.mcp_client import MCPClientError
from kali_mcp.studio.service_mcp_connections import (
    add_connection,
    discover_and_import,
)


class TestAddConnection:
    def test_returns_connection_dict_with_all_fields(self):
        result = add_connection(
            db=None,
            connection_id="conn_1",
            transport="stdio",
            command=["npx", "mcp-server-fs"],
            timeout=60.0,
            headers={"X-Test": "1"},
        )
        assert result == {
            "connection_id": "conn_1",
            "transport": "stdio",
            "url": None,
            "command": ["npx", "mcp-server-fs"],
            "timeout": 60.0,
        }

    def test_defaults(self):
        result = add_connection(
            db=None,
            connection_id="c",
            transport="sse",
            url="http://localhost:8080/sse",
        )
        assert result["connection_id"] == "c"
        assert result["transport"] == "sse"
        assert result["url"] == "http://localhost:8080/sse"
        assert result["command"] is None
        assert result["timeout"] == 30.0

    def test_streamable_http_with_headers(self):
        result = add_connection(
            db=None,
            connection_id="c",
            transport="streamable-http",
            url="http://localhost:8080/mcp",
            headers={"Authorization": "Bearer x"},
        )
        assert result["transport"] == "streamable-http"
        assert result["url"] == "http://localhost:8080/mcp"
        assert result["command"] is None

    def test_unsupported_transport_raises(self):
        with pytest.raises(MCPClientError, match="unsupported transport"):
            add_connection(db=None, connection_id="c", transport="websocket")

    def test_sse_requires_url(self):
        with pytest.raises(MCPClientError, match="requires a url"):
            add_connection(db=None, connection_id="c", transport="sse")

    def test_stdio_requires_command(self):
        with pytest.raises(MCPClientError, match="requires a command"):
            add_connection(db=None, connection_id="c", transport="stdio")


class TestDiscoverAndImport:
    async def test_success_returns_imported_tools(self):
        db = object()
        client = AsyncMock()
        imported = [
            {
                "row_id": 1,
                "tool_id": "external_mcp:conn_1:read_file",
                "name": "read_file",
                "provider": "external_mcp",
                "visibility": "internal",
            },
            {
                "row_id": 2,
                "tool_id": "external_mcp:conn_1:list_dir",
                "name": "list_dir",
                "provider": "external_mcp",
                "visibility": "internal",
            },
        ]
        with patch(
            "kali_mcp.studio.service_mcp_connections.import_external_mcp_tools",
            new=AsyncMock(return_value=imported),
        ) as mock_import:
            result = await discover_and_import(db, "conn_1", client, visibility="internal")
        assert result == imported
        mock_import.assert_awaited_once_with(db, "conn_1", client, visibility="internal")

    async def test_default_visibility(self):
        db = object()
        client = AsyncMock()
        with patch(
            "kali_mcp.studio.service_mcp_connections.import_external_mcp_tools",
            new=AsyncMock(return_value=[]),
        ) as mock_import:
            await discover_and_import(db, "conn_1", client)
        mock_import.assert_awaited_once_with(db, "conn_1", client, visibility="internal")

    async def test_mcp_client_error_re_raised(self):
        db = object()
        client = AsyncMock()
        with patch(
            "kali_mcp.studio.service_mcp_connections.import_external_mcp_tools",
            new=AsyncMock(side_effect=MCPClientError("boom")),
        ):
            with pytest.raises(MCPClientError, match="boom"):
                await discover_and_import(db, "conn_1", client)


class TestTestConnection:
    def test_returns_true_on_success(self):
        client = AsyncMock()
        client.list_tools = AsyncMock(return_value=[])
        assert smc.test_connection(client) is True
        client.list_tools.assert_awaited_once()

    def test_returns_false_when_list_tools_fails(self):
        client = AsyncMock()
        client.list_tools = AsyncMock(side_effect=MCPClientError("down"))
        assert smc.test_connection(client) is False

    def test_returns_false_when_connect_fails(self):
        client = AsyncMock()
        client.__aenter__ = AsyncMock(side_effect=MCPClientError("connect failed"))
        assert smc.test_connection(client) is False
