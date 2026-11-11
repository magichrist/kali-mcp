"""Unit tests for command sanitization helpers."""

from __future__ import annotations

from kmcp.security import quote_argument, sanitize_command_parts


def test_sanitize_strings():
    assert sanitize_command_parts(["a", "b"]) == ["a", "b"]


def test_sanitize_mixed_types():
    assert sanitize_command_parts(["echo", 42]) == ["echo", "42"]


def test_quote_basic():
    assert quote_argument("hello") == "hello"


def test_quote_with_space():
    assert quote_argument("hello world") == "'hello world'"
