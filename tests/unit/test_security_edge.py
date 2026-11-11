"""Edge-case tests for security.py sanitization and quoting."""

from __future__ import annotations

import pytest

from kmcp.security import quote_argument, sanitize_command_parts


class TestSanitizeCommandParts:
    def test_empty_list(self):
        assert sanitize_command_parts([]) == []

    def test_coerces_int(self):
        assert sanitize_command_parts([1, 0, -5]) == ["1", "0", "-5"]

    def test_coerces_float(self):
        assert sanitize_command_parts(["ping", 8.8]) == ["ping", "8.8"]

    def test_none_becomes_none_string(self):
        assert sanitize_command_parts(["echo", None]) == ["echo", "None"]

    def test_unicode_preserved(self):
        assert sanitize_command_parts(["echo", "héllo→wörld"]) == [
            "echo",
            "héllo→wörld",
        ]

    def test_shell_metacharacters_preserved_as_literal_args(self):
        # Sanitization must not alter content — injection safety comes from
        # exec-without-shell, not from stripping characters.
        parts = sanitize_command_parts(["echo", "a; rm -rf /", "$(whoami)", "`id`"])
        assert parts[1] == "a; rm -rf /"
        assert parts[2] == "$(whoami)"

    def test_bool_coerces(self):
        assert sanitize_command_parts(["set", True]) == ["set", "True"]


class TestQuoteArgument:
    def test_quotes_empty_string(self):
        assert quote_argument("") == "''"

    def test_quotes_tabs(self):
        assert quote_argument("a\tb") == "'a\tb'"

    def test_quotes_single_quotes(self):
        result = quote_argument("it's")
        assert "it" in result and "s" in result

    def test_plain_word_unquoted(self):
        assert quote_argument("nmap") == "nmap"

    @pytest.mark.parametrize("value", ["hello world", "a;b", "a$b", "a`b", "a&b", "a|b"])
    def test_dangerous_chars_are_quoted(self, value):
        assert quote_argument(value).startswith("'")
