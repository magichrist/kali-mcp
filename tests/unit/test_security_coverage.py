"""Unit tests for security.py — command sanitization and argument quoting."""

from __future__ import annotations

import pytest

from kmcp.security import quote_argument, sanitize_command_parts


class TestSanitizeCommandParts:
    def test_passthrough_strings(self):
        assert sanitize_command_parts(["a", "b"]) == ["a", "b"]

    def test_mixed_types_coerced_to_str(self):
        assert sanitize_command_parts(["echo", 42]) == ["echo", "42"]

    def test_empty_list(self):
        assert sanitize_command_parts([]) == []

    def test_none_coerced_to_none_string(self):
        assert sanitize_command_parts(["echo", None]) == ["echo", "None"]

    def test_bool_coerced(self):
        assert sanitize_command_parts(["set", True]) == ["set", "True"]

    def test_float_coerced(self):
        assert sanitize_command_parts(["ping", 8.8]) == ["ping", "8.8"]

    def test_unicode_preserved(self):
        assert sanitize_command_parts(["echo", "héllo→wörld"]) == [
            "echo",
            "héllo→wörld",
        ]

    def test_shell_metacharacters_preserved_as_literal_args(self):
        parts = sanitize_command_parts(["echo", "a; rm -rf /", "$(whoami)", "`id`"])
        assert parts[1] == "a; rm -rf /"
        assert parts[2] == "$(whoami)"
        assert parts[3] == "`id`"


class TestQuoteArgument:
    def test_plain_word_unquoted(self):
        assert quote_argument("nmap") == "nmap"

    def test_basic_word(self):
        assert quote_argument("hello") == "hello"

    def test_with_space(self):
        assert quote_argument("hello world") == "'hello world'"

    def test_empty_string(self):
        assert quote_argument("") == "''"

    def test_tabs(self):
        assert quote_argument("a\tb") == "'a\tb'"

    def test_single_quotes(self):
        result = quote_argument("it's")
        assert result.startswith("'")
        assert result.endswith("'")

    @pytest.mark.parametrize(
        "value", ["hello world", "a;b", "a$b", "a`b", "a&b", "a|b", "a>b", "a<b"]
    )
    def test_dangerous_chars_are_quoted(self, value):
        assert quote_argument(value).startswith("'")
