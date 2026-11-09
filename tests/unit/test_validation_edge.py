"""Edge-case tests for validators: type abuse, boundaries, unicode."""

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


class TestTypeAbuse:
    def test_validate_ip_with_int_is_accepted_as_integer_ip(self):
        # stdlib quirk: ip_address(12345) → 0.0.48.57
        assert validate_ip(12345) is None  # type: ignore[arg-type]

    def test_validate_ip_with_float_raises(self):
        with pytest.raises((ValueError, TypeError)):
            validate_ip(1.5)  # type: ignore[arg-type]

    def test_validate_ip_with_none(self):
        with pytest.raises((ValueError, TypeError)):
            validate_ip(None)  # type: ignore[arg-type]

    def test_validate_domain_with_none(self):
        with pytest.raises((ValueError, TypeError)):
            validate_domain(None)  # type: ignore[arg-type]

    def test_validate_url_with_none(self):
        with pytest.raises((ValueError, TypeError)):
            validate_url(None)  # type: ignore[arg-type]

    def test_validate_ports_with_none(self):
        with pytest.raises((ValueError, TypeError)):
            validate_ports(None)  # type: ignore[arg-type]


class TestIPBoundaries:
    @pytest.mark.parametrize("value", ["127.0.0.0", "127.0.0.1"])
    def test_valid_boundaries(self, value):
        assert validate_ip(value) is None

    @pytest.mark.parametrize("value", ["256.1.1.1", "1.2.3.4.5", "127.0.0.1/8", "", " "])
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            validate_ip(value)


class TestDomainEdge:
    @pytest.mark.parametrize("value", ["a.io", "x.y.z.w.example.com", "UPPER.COM"])
    def test_valid_variants(self, value):
        assert validate_domain(value) is None

    @pytest.mark.parametrize("value", ["-leading.com", "trailing-.com", "..", "com"])
    def test_invalid_variants(self, value):
        with pytest.raises(ValueError):
            validate_domain(value)


class TestURLEdge:
    def test_uppercase_scheme_accepted(self):
        # urlparse lowercases the scheme, so HTTPs:// is treated as https
        assert validate_url("HTTPs://example.com") is None

    def test_missing_netloc(self):
        with pytest.raises(ValueError):
            validate_url("http://")

    def test_with_query_and_fragment(self):
        assert validate_url("https://e.com/a?b=c#d") is None


class TestPortBoundaries:
    def test_min_port(self):
        assert validate_ports("1") is None

    def test_max_port(self):
        assert validate_ports("65535") is None

    def test_boundary_range(self):
        assert validate_ports("1-65535") is None

    @pytest.mark.parametrize("value", ["0", "65536", "80-", "-80", "80--443", "a", "80, ", ""])
    def test_invalid(self, value):
        with pytest.raises(ValueError):
            validate_ports(value)


class TestTimeoutBoundaries:
    def test_float_accepted(self):
        assert validate_timeout(1.5) is None  # type: ignore[arg-type]

    def test_negative(self):
        with pytest.raises(ValueError):
            validate_timeout(-1)

    def test_custom_bounds(self):
        assert validate_timeout(10, min_val=5, max_val=20) is None
        with pytest.raises(ValueError):
            validate_timeout(3, min_val=5, max_val=20)


class TestRequiredMultiField:
    def test_multiple_fields_all_present(self):
        assert validate_required({"a": "1", "b": "2", "c": "3"}, "a", "b", "c") is None

    def test_reports_first_missing(self):
        with pytest.raises(ValueError, match="b"):
            validate_required({"a": "1"}, "a", "b")


class TestEnumCustom:
    def test_case_sensitive(self):
        with pytest.raises(ValueError):
            validate_enum("SMB", ["smb"])

    def test_allowed_message_lists_options(self):
        with pytest.raises(ValueError, match="smb, ssh"):
            validate_enum("bad", ["smb", "ssh"])


class TestCIDREdge:
    def test_ipv6_cidr(self):
        assert validate_cidr("127.0.0.1/0") is None

    def test_host_bits_automatically_reset(self):
        # strict=False allows host bits set
        assert validate_cidr("127.0.0.1/8") is None
