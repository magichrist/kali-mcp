"""Additional unit tests for the scope enforcement module (kali_mcp/scope.py).

Covers exact match, excluded targets, expiration fail-closed, and edge cases
complementing tests/unit/test_scope.py.
"""

from __future__ import annotations

import pytest

from kali_mcp.scope import Scope, check_scope, is_target_allowed, is_operation_allowed


class TestExactMatch:
    def test_exact_ip_match(self):
        scope = Scope(allowed_targets=["10.0.0.1"])
        assert is_target_allowed("10.0.0.1", scope) is True
        assert is_target_allowed("10.0.0.2", scope) is False

    def test_exact_domain_match(self):
        scope = Scope(allowed_targets=["example.com"])
        assert is_target_allowed("example.com", scope) is True
        assert is_target_allowed("www.example.com", scope) is False

    def test_subdomain_not_exact_match(self):
        scope = Scope(allowed_targets=["example.com"])
        assert is_target_allowed("sub.example.com", scope) is False


class TestExcludedTargets:
    def test_excluded_denies_even_when_allowed(self):
        scope = Scope(
            allowed_targets=["10.0.0.*"], excluded_targets=["10.0.0.1"]
        )
        assert is_target_allowed("10.0.0.5", scope) is True
        assert is_target_allowed("10.0.0.1", scope) is False

    def test_excluded_without_allowed_list(self):
        scope = Scope(excluded_targets=["10.0.0.1"])
        assert is_target_allowed("10.0.0.2", scope) is True
        assert is_target_allowed("10.0.0.1", scope) is False

    def test_excluded_glob_pattern(self):
        scope = Scope(excluded_targets=["10.0.0.*"])
        assert is_target_allowed("10.0.1.1", scope) is True
        assert is_target_allowed("10.0.0.99", scope) is False


class TestExpirationFailClosed:
    def test_expired_scope_denies_all_targets(self):
        scope = Scope(expiration="2000-01-01T00:00:00Z")
        assert scope.is_expired() is True
        assert is_target_allowed("10.0.0.1", scope) is False
        assert is_target_allowed("example.com", scope) is False

    def test_expired_scope_check_scope_raises(self):
        scope = Scope(expiration="2000-01-01T00:00:00Z")
        with pytest.raises(ValueError, match="has expired"):
            check_scope("10.0.0.1", "nmap", scope)

    def test_none_expiration_not_expired(self):
        scope = Scope(expiration=None)
        assert scope.is_expired() is False
        assert is_target_allowed("anything", scope) is True


class TestOperationMatchingExtended:
    def test_operation_case_sensitive(self):
        scope = Scope(allowed_operations=["Nmap"])
        assert is_operation_allowed("Nmap", scope) is True
        assert is_operation_allowed("nmap", scope) is False

    def test_none_operation_allowed(self):
        scope = Scope(allowed_operations=["nmap"])
        assert is_operation_allowed(None, scope) is True

    def test_empty_string_operation_allowed(self):
        scope = Scope(allowed_operations=["nmap"])
        assert is_operation_allowed("", scope) is True
