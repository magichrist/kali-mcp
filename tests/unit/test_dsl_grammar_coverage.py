"""Extra coverage tests for the DSL tokenizer (dsl/grammar.py).

Targets the error paths and literal/operator/field-ref branches the
existing tests do not exercise: malformed field references, unterminated
strings, comparison operators, floats, booleans, null, and unexpected
characters.
"""

from __future__ import annotations

import pytest

from kmcp.workflow.dsl.grammar import (
    FIELD_REF,
    STRING,
    Token,
    TokenError,
    tokenize,
)


def tok(text: str):
    return tokenize(text)


class TestFieldRefs:
    def test_field_ref_variants(self):
        tokens = tok("{{steps.dns.resolved_hosts}} {{inputs.target}} {{target}}")
        kinds = [t.type for t in tokens if t.type != "EOF"]
        assert kinds == [FIELD_REF, FIELD_REF, FIELD_REF]
        assert tokens[0].value == ("steps", ".dns.resolved_hosts")
        assert tokens[1].value == ("inputs", ".target")
        assert tokens[2].value == ("target", "")

    def test_malformed_field_reference_raises(self):
        with pytest.raises(TokenError, match="malformed field reference"):
            tokenize("{{not-a-valid-ref}}")

    def test_malformed_field_reference_reports_line_col(self):
        with pytest.raises(TokenError) as exc:
            tokenize("x {{bad}}\n")
        assert exc.value.args[0].startswith("malformed field reference at line 1, col")


class TestStrings:
    def test_unterminated_string_raises(self):
        with pytest.raises(TokenError, match="unterminated string"):
            tokenize('"never closed')

    def test_escaped_string(self):
        tokens = tokenize('"a\\"b \\\\c"')
        str_tok = next(t for t in tokens if t.type == STRING)
        assert str_tok.value == 'a"b \\c'


class TestPunctuationAndOperators:
    def test_single_char_operators(self):
        tokens = tokenize("> < ==")
        types = [t.type for t in tokens if t.type != "EOF"]
        assert types == ["GT", "LT", "EQ"]

    def test_multi_char_operators(self):
        tokens = tokenize(">= <= !=")
        types = [t.type for t in tokens if t.type != "EOF"]
        assert types == ["GE", "LE", "NE"]

    def test_punctuation(self):
        tokens = tokenize("{ } [ ] : , .")
        types = [t.type for t in tokens if t.type != "EOF"]
        assert types == ["LBRACE", "RBRACE", "LBRACKET", "RBRACKET", "COLON", "COMMA", "DOT"]


class TestNumbersBoolsNull:
    def test_integer_and_float(self):
        tokens = tokenize("42 -7 3.14 0.5")
        types = [(t.type, t.value) for t in tokens if t.type != "EOF"]
        assert ("INTEGER", 42) in types
        assert ("INTEGER", -7) in types
        assert ("FLOAT", 3.14) in types
        assert ("FLOAT", 0.5) in types

    def test_bool_and_null(self):
        tokens = tokenize("true false null")
        types = [(t.type, t.value) for t in tokens if t.type != "EOF"]
        assert ("BOOL", True) in types
        assert ("BOOL", False) in types
        assert ("NULL", None) in types

    def test_identifier_vs_keyword(self):
        tokens = tokenize("id name enum array object target")
        values = [t.value for t in tokens if t.type != "EOF"]
        assert values == ["id", "name", "enum", "array", "object", "target"]
        assert all(t.type == "IDENTIFIER" for t in tokens if t.type != "EOF")


class TestUnexpectedCharacter:
    def test_unexpected_character_raises(self):
        with pytest.raises(TokenError, match="unexpected character"):
            tokenize("id: x @")

    def test_unexpected_character_reports_line_col(self):
        with pytest.raises(TokenError) as exc:
            tokenize("id: x\n@")
        assert "line 2, col 1" in exc.value.args[0]


class TestTokenDataclass:
    def test_token_repr_and_equality(self):
        t = Token(STRING, "hi", 2, 5)
        assert t.type == STRING
        assert t.value == "hi"
        assert t.line == 2
        assert t.col == 5
        assert Token(STRING, "hi", 2, 5) == t
        assert hash(t) == hash(Token(STRING, "hi", 2, 5))
