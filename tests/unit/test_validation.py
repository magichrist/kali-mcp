"""Unit tests for parameter validators."""

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

    def test_fails_without_field(self):
        with pytest.raises(ValueError, match="x"):
            validate_required({}, "x")

    def test_fails_with_empty_string(self):
        with pytest.raises(ValueError):
            validate_required({"x": "  "}, "x")


class TestIP:
    @pytest.mark.parametrize("value", ["192.168.1.1", "::1", "10.0.0.1"])
    def test_valid(self, value):
        assert validate_ip(value) is None

    def test_invalid(self):
        with pytest.raises(ValueError):
            validate_ip("not_an_ip")


class TestCIDR:
    @pytest.mark.parametrize("value", ["10.0.0.0/8", "192.168.1.1/32"])
    def test_valid(self, value):
        assert validate_cidr(value) is None

    def test_invalid(self):
        with pytest.raises(ValueError):
            validate_cidr("10.0.0.0/33")


class TestDomain:
    @pytest.mark.parametrize("value", ["example.com", "sub.example.com"])
    def test_valid(self, value):
        assert validate_domain(value) is None

    def test_invalid(self):
        with pytest.raises(ValueError):
            validate_domain("not valid domain!")


class TestURL:
    @pytest.mark.parametrize(
        "value", ["https://example.com", "http://10.0.0.1:8080/path"]
    )
    def test_valid(self, value):
        assert validate_url(value) is None

    def test_invalid_scheme(self):
        with pytest.raises(ValueError):
            validate_url("ftp://bad")


class TestTimeout:
    @pytest.mark.parametrize("value", [60, "30", 1, 3600])
    def test_valid(self, value):
        assert validate_timeout(value) is None

    @pytest.mark.parametrize("value", [0, 9999, "abc"])
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            validate_timeout(value)


class TestEnum:
    def test_valid(self):
        assert validate_enum("smb", ["smb", "ssh"]) is None

    def test_invalid(self):
        with pytest.raises(ValueError):
            validate_enum("bad", ["smb", "ssh"])


class TestPorts:
    @pytest.mark.parametrize("value", ["80", "80-443", "80,443,8080"])
    def test_valid(self, value):
        assert validate_ports(value) is None

    def test_port_above_65535(self):
        with pytest.raises(ValueError):
            validate_ports("99999")

    def test_reversed_range(self):
        with pytest.raises(ValueError):
            validate_ports("443-80")
