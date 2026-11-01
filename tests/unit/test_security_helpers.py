"""Unit tests for security helpers (command sanitization)."""

from shlex import quote as _shlex_quote

from security import quote_argument, sanitize_command_parts


def test_sanitize_command_parts():
    assert sanitize_command_parts(["a", "b"]) == ["a", "b"]


def test_quote_argument():
    assert quote_argument("it's") == _shlex_quote("it's")
