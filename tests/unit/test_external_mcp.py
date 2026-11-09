"""Tests for the external MCP client (Playbook Studio Phase 3, Task B).

Unit tests only — no live network connections. Tests client initialization,
validation, and result redaction.
"""

from __future__ import annotations

import pytest

from kali_mcp.studio.mcp_client import (
    DEFAULT_TIMEOUT,
    ExternalMCPClient,
    MCPClientError,
    redact_result,
)


class TestClientInit:
    def test_stdio_requires_command(self):
        with pytest.raises(MCPClientError, match="stdio requires"):
            ExternalMCPClient("stdio")

    def test_sse_requires_url(self):
        with pytest.raises(MCPClientError, match="sse requires a url"):
            ExternalMCPClient("sse")

    def test_streamable_http_requires_url(self):
        with pytest.raises(MCPClientError, match="streamable-http requires a url"):
            ExternalMCPClient("streamable-http")

    def test_invalid_transport_rejected(self):
        with pytest.raises(MCPClientError, match="unsupported transport"):
            ExternalMCPClient("websocket")

    def test_valid_stdio_config(self):
        client = ExternalMCPClient("stdio", command=["npx", "some-mcp-server"])
        assert client.transport == "stdio"
        assert client.command == ["npx", "some-mcp-server"]
        assert client.timeout == DEFAULT_TIMEOUT

    def test_valid_sse_config(self):
        client = ExternalMCPClient("sse", url="http://localhost:8080/sse")
        assert client.transport == "sse"
        assert client.url == "http://localhost:8080/sse"

    def test_valid_streamable_http_config(self):
        client = ExternalMCPClient("streamable-http", url="http://localhost:8080/mcp", timeout=60)
        assert client.transport == "streamable-http"
        assert client.timeout == 60

    def test_custom_timeout(self):
        client = ExternalMCPClient("stdio", command=["x"], timeout=120)
        assert client.timeout == 120


class TestRedaction:
    def test_redacts_secret_keys(self):
        result = redact_result({"api_key": "sk-1234567890abcdef", "name": "tool"})
        assert result["api_key"] == "***REDACTED***"
        assert result["name"] == "tool"

    def test_redacts_password_key(self):
        result = redact_result({"password": "hunter2"})
        assert result["password"] == "***REDACTED***"

    def test_redacts_token_key(self):
        result = redact_result({"access_token": "ghp_abcdef123456"})
        assert result["access_token"] == "***REDACTED***"

    def test_redacts_nested_dict(self):
        result = redact_result({"data": {"credentials": {"password": "x"}}})
        assert result["data"]["credentials"]["password"] == "***REDACTED***"

    def test_redacts_secret_patterns_in_strings(self):
        result = redact_result({"output": "token sk_live_1234567890abcdef done"})
        assert "***REDACTED***" in result["output"]
        assert "sk_live" not in result["output"]

    def test_redacts_base64_like_tokens(self):
        result = redact_result({"blob": "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789=="})
        assert "***REDACTED***" in result["blob"]

    def test_passthrough_non_secret(self):
        result = redact_result({"stdout": "hello world", "exit_code": 0})
        assert result["stdout"] == "hello world"
        assert result["exit_code"] == 0

    def test_redacts_list_of_dicts(self):
        result = redact_result({"items": [{"password": "secret1"}, {"password": "secret2"}]})
        assert result["items"][0]["password"] == "***REDACTED***"
        assert result["items"][1]["password"] == "***REDACTED***"

    def test_non_dict_returns_unchanged(self):
        assert redact_result("just a string") == "just a string"
        assert redact_result([1, 2, 3]) == [1, 2, 3]
        assert redact_result(42) == 42


class TestClientError:
    def test_mcp_client_error_is_exception(self):
        assert issubclass(MCPClientError, Exception)

    def test_default_timeout(self):
        assert DEFAULT_TIMEOUT == 30
