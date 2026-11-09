"""Unit tests for validation.py — all validators with valid and invalid inputs."""

from __future__ import annotations

import pytest

from kali_mcp.validation import (
    validate_cidr,
    validate_domain,
    validate_enum,
    validate_ip,
    validate_ports,
    validate_required,
    validate_timeout,
    validate_url,
)


class TestRequired:
    def test_passes_with_field(self):
        assert validate_required({"x": "1"}, "x") is None

    def test_multiple_fields_all_present(self):
        assert validate_required({"a": "1", "b": "2", "c": "3"}, "a", "b", "c") is None

    def test_fails_without_field(self):
        with pytest.raises(ValueError, match="x"):
            validate_required({}, "x")

    def test_fails_with_empty_string(self):
        with pytest.raises(ValueError):
            validate_required({"x": "  "}, "x")

    def test_reports_first_missing(self):
        with pytest.raises(ValueError, match="b"):
            validate_required({"a": "1"}, "a", "b")


class TestIP:
    @pytest.mark.parametrize("value", ["127.0.0.1"])
    def test_valid(self, value):
        assert validate_ip(value) is None

    @pytest.mark.parametrize(
        "value", ["not_an_ip", "256.1.1.1", "1.2.3.4.5", "127.0.0.1/8", "", " "]
    )
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            validate_ip(value)


class TestCIDR:
    @pytest.mark.parametrize("value", ["127.0.0.0/8", "127.0.0.1/32", "127.0.0.1/0", "127.0.0.1/8"])
    def test_valid(self, value):
        assert validate_cidr(value) is None

    def test_invalid_prefix_len(self):
        with pytest.raises(ValueError):
            validate_cidr("127.0.0.0/33")

    def test_invalid(self):
        with pytest.raises(ValueError):
            validate_cidr("not_cidr")


class TestDomain:
    @pytest.mark.parametrize(
        "value", ["example.com", "sub.example.com", "a.io", "x.y.z.w.example.com", "UPPER.COM"]
    )
    def test_valid(self, value):
        assert validate_domain(value) is None

    @pytest.mark.parametrize(
        "value", ["not valid domain!", "-leading.com", "trailing-.com", "..", "com"]
    )
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            validate_domain(value)


class TestURL:
    @pytest.mark.parametrize(
        "value", ["https://example.com", "http://127.0.0.1:8080/path", "https://e.com/a?b=c#d"]
    )
    def test_valid(self, value):
        assert validate_url(value) is None

    def test_uppercase_scheme_accepted(self):
        assert validate_url("HTTPs://example.com") is None

    def test_invalid_scheme(self):
        with pytest.raises(ValueError):
            validate_url("ftp://bad")

    def test_missing_netloc(self):
        with pytest.raises(ValueError):
            validate_url("http://")


class TestTimeout:
    @pytest.mark.parametrize("value", [60, "30", 1, 3600, 1.5])
    def test_valid(self, value):
        assert validate_timeout(value) is None

    @pytest.mark.parametrize("value", [0, 9999, "abc", -1])
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            validate_timeout(value)

    def test_custom_bounds(self):
        assert validate_timeout(10, min_val=5, max_val=20) is None
        with pytest.raises(ValueError):
            validate_timeout(3, min_val=5, max_val=20)


class TestEnum:
    def test_valid(self):
        assert validate_enum("smb", ["smb", "ssh"]) is None

    def test_invalid(self):
        with pytest.raises(ValueError):
            validate_enum("bad", ["smb", "ssh"])

    def test_case_sensitive(self):
        with pytest.raises(ValueError):
            validate_enum("SMB", ["smb"])

    def test_error_message_lists_options(self):
        with pytest.raises(ValueError, match="smb, ssh"):
            validate_enum("bad", ["smb", "ssh"])


class TestPorts:
    @pytest.mark.parametrize("value", ["80", "80-443", "80,443,8080", "1", "65535", "1-65535"])
    def test_valid(self, value):
        assert validate_ports(value) is None

    def test_port_above_65535(self):
        with pytest.raises(ValueError):
            validate_ports("99999")

    def test_reversed_range(self):
        with pytest.raises(ValueError):
            validate_ports("443-80")

    @pytest.mark.parametrize("value", ["0", "65536", "80-", "-80", "80--443", "a", "80, ", ""])
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            validate_ports(value)
