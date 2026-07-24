"""Parameter validators for common input types."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse


def validate_required(arguments: dict, *fields: str) -> None:
    """Raise ValueError if any required field is missing or empty."""
    for field in fields:
        if field not in arguments:
            raise ValueError(f"Missing required parameter: {field}")
        val = arguments[field]
        if isinstance(val, str) and not val.strip():
            raise ValueError(f"Parameter '{field}' must not be empty")


def validate_ip(value: str, label: str = "IP") -> None:
    """Raise ValueError if value is not a valid IP address."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise ValueError(f"Invalid {label}: {value}")


def validate_cidr(value: str, label: str = "CIDR") -> None:
    """Raise ValueError if value is not valid CIDR notation."""
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError:
        raise ValueError(f"Invalid {label}: {value}")


def validate_domain(value: str, label: str = "domain") -> None:
    """Raise ValueError if value is not a valid domain name."""
    pattern = re.compile(
        r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,}$"
    )
    if not pattern.match(value):
        raise ValueError(f"Invalid {label}: {value}")


def validate_url(value: str, label: str = "URL") -> None:
    """Raise ValueError if value is not a valid HTTP/HTTPS URL."""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid {label}: must start with http:// or https://")
    if not parsed.netloc:
        raise ValueError(f"Invalid {label}: {value}")


def validate_timeout(value: int | str, min_val: int = 1, max_val: int = 3600) -> None:
    """Raise ValueError if timeout is out of range."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Timeout must be a number, got {value!r}")
    if value < min_val or value > max_val:
        raise ValueError(f"Timeout must be between {min_val} and {max_val}, got {value}")


def validate_enum(value: str, allowed: list[str], label: str = "value") -> None:
    """Raise ValueError if value is not in allowed list."""
    if value not in allowed:
        raise ValueError(f"Invalid {label}: '{value}'. Allowed: {', '.join(allowed)}")


def validate_ports(value: str, label: str = "ports") -> None:
    """Raise ValueError if value is not a valid port specification."""
    pattern = re.compile(r"^(\d{1,5}(-\d{1,5})?)(,\d{1,5}(-\d{1,5})?)*$")
    if not pattern.match(value):
        raise ValueError(f"Invalid {label}: {value}")
    for part in value.split(","):
        if "-" in part:
            start, end = part.split("-", 1)
            s, e = int(start), int(end)
            if s < 1 or e > 65535 or s > e:
                raise ValueError(f"Invalid {label} range: {part}")
        else:
            p = int(part)
            if p < 1 or p > 65535:
                raise ValueError(f"Invalid {label}: {part}")
