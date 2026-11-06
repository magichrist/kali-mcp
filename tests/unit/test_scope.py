"""Unit tests for the scope enforcement module (kali_mcp/scope.py)."""

from __future__ import annotations

import pytest

from kali_mcp.scope import (
    Scope,
    check_scope,
    is_operation_allowed,
    is_target_allowed,
    load_scope,
)


class TestScopeDefaults:
    def test_default_scope_allows_everything(self):
        scope = Scope()
        assert scope.is_empty() is True
        assert is_target_allowed("127.0.0.1", scope) is True
        assert is_target_allowed("example.com", scope) is True
        assert is_operation_allowed("generic_command", scope) is True
        assert is_operation_allowed("nmap", scope) is True
        check_scope("any.target", "any_tool", scope)  # does not raise

    def test_expired_scope_denies_all(self):
        scope = Scope(expiration="2000-01-01T00:00:00Z")
        assert scope.is_expired() is True
        assert is_target_allowed("127.0.0.1", scope) is False
        with pytest.raises(ValueError, match="has expired"):
            check_scope("127.0.0.1", "nmap", scope)


class TestTargetMatching:
    def test_exact_match_allowed(self):
        scope = Scope(allowed_targets=["127.0.0.1", "example.com"])
        assert is_target_allowed("127.0.0.1", scope) is True
        assert is_target_allowed("example.com", scope) is True

    def test_wildcard_allows_all(self):
        scope = Scope(allowed_targets=["*"])
        assert is_target_allowed("127.0.0.1", scope) is True
        assert is_target_allowed("evil.example.com", scope) is True

    def test_not_in_allowed_list_denied(self):
        scope = Scope(allowed_targets=["127.0.0.1"])
        assert is_target_allowed("blocked.example.com", scope) is False

    def test_excluded_takes_precedence(self):
        scope = Scope(
            allowed_targets=["*.example.com"], excluded_targets=["node.example.com"]
        )
        assert is_target_allowed("api.example.com", scope) is True
        assert is_target_allowed("node.example.com", scope) is False

    def test_glob_pattern_match(self):
        scope = Scope(allowed_targets=["*.example.com"])
        assert is_target_allowed("api.example.com", scope) is True
        assert is_target_allowed("api.other.org", scope) is False

    def test_none_target_allowed(self):
        scope = Scope(allowed_targets=["127.0.0.1"])
        assert is_target_allowed(None, scope) is True
        assert is_target_allowed("", scope) is True


class TestOperationMatching:
    def test_exact_operation_allowed(self):
        scope = Scope(allowed_operations=["nmap", "masscan"])
        assert is_operation_allowed("nmap", scope) is True
        assert is_operation_allowed("generic_command", scope) is False

    def test_empty_operations_allows_all(self):
        scope = Scope(allowed_operations=[])
        assert is_operation_allowed("nmap", scope) is True


class TestCheckScope:
    def test_raises_on_out_of_scope_target(self):
        scope = Scope(allowed_targets=["127.0.0.1"])
        with pytest.raises(ValueError, match="not in allowed scope targets"):
            check_scope("blocked.example.com", "nmap", scope)

    def test_raises_on_excluded_target(self):
        scope = Scope(excluded_targets=["127.0.0.1"])
        with pytest.raises(ValueError, match="is excluded by scope"):
            check_scope("127.0.0.1", "nmap", scope)

    def test_raises_on_disallowed_operation(self):
        scope = Scope(allowed_operations=["nmap"])
        with pytest.raises(ValueError, match="not in allowed scope operations"):
            check_scope("127.0.0.1", "generic_command", scope)

    def test_passes_when_in_scope(self):
        scope = Scope(allowed_targets=["127.0.0.1"], allowed_operations=["nmap"])
        check_scope("127.0.0.1", "nmap", scope)  # does not raise


class TestLoadScope:
    def test_env_allowed_targets(self, monkeypatch):
        monkeypatch.setenv(
            "MCP_SCOPE_ALLOWED_TARGETS", "127.0.0.0/8,example.com"
        )
        monkeypatch.setenv("MCP_SCOPE_EXCLUDED_TARGETS", "127.0.0.1")
        monkeypatch.setenv("MCP_SCOPE_ALLOWED_OPERATIONS", "nmap")
        monkeypatch.setenv("MCP_SCOPE_POLICY", "safe_active")
        scope = load_scope()
        assert scope.allowed_targets == ("127.0.0.0/8", "example.com")
        assert scope.excluded_targets == ("127.0.0.1",)
        assert scope.allowed_operations == ("nmap",)
        assert scope.policy == "safe_active"

    def test_no_env_means_allow_all(self, monkeypatch):
        for k in (
            "MCP_SCOPE_ALLOWED_TARGETS",
            "MCP_SCOPE_EXCLUDED_TARGETS",
            "MCP_SCOPE_ALLOWED_OPERATIONS",
            "MCP_SCOPE_EXPIRATION",
            "MCP_SCOPE_POLICY",
        ):
            monkeypatch.delenv(k, raising=False)
        scope = load_scope()
        assert scope.is_empty()
        assert is_target_allowed("anything", scope)
        assert is_operation_allowed("anything", scope)
        assert scope.policy == "safe_active"

    def test_convenience_check_scope_raises(self, monkeypatch):
        monkeypatch.setenv("MCP_SCOPE_ALLOWED_TARGETS", "127.0.0.1")
        with pytest.raises(ValueError):
            check_scope("blocked.example.com", "nmap")
