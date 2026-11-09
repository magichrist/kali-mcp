"""DSL tokenizer for the Playbook Studio workflow language.

Tokenizes DSL text (see docs/visual/03_DSL_SPECIFICATION.md §3) into a stream
of :class:`Token` instances consumed by :mod:`kali_mcp.workflow.dsl.parser`.

The grammar is intentionally small and injection-safe: variable expressions are
restricted to ``{{inputs.X}}``, ``{{steps.SID.FIELD}}``, and ``{{target}}``.
No shell constructs are lexed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Token types ──────────────────────────────────────────────────────────────

LBRACE = "LBRACE"  # {
RBRACE = "RBRACE"  # }
LBRACKET = "LBRACKET"  # [
RBRACKET = "RBRACKET"  # ]
COLON = "COLON"  # :
COMMA = "COMMA"  # ,
DOT = "DOT"  # .
GT = "GT"  # >
LT = "LT"  # <
GE = "GE"  # >=
LE = "LE"  # <=
EQ = "EQ"  # ==
NE = "NE"  # !=

IDENTIFIER = "IDENTIFIER"
STRING = "STRING"
FIELD_REF = "FIELD_REF"  # {{...}}
INTEGER = "INTEGER"
FLOAT = "FLOAT"
BOOL = "BOOL"
NULL = "NULL"
EOF = "EOF"

# Single-character punctuation → token type
_PUNCT: dict[str, str] = {
    "{": LBRACE,
    "}": RBRACE,
    "[": LBRACKET,
    "]": RBRACKET,
    ":": COLON,
    ",": COMMA,
    ".": DOT,
}

# Multi-char operators (checked before single-char < / > / =)
_OPERATORS: dict[str, str] = {
    ">=": GE,
    "<=": LE,
    "==": EQ,
    "!=": NE,
    ">": GT,
    "<": LT,
}

# Keywords that are also valid identifiers in expression positions.
_KEYWORDS = frozenset(
    {
        "id",
        "name",
        "version",
        "description",
        "inputs",
        "execution",
        "steps",
        "outputs",
        "module",
        "tool",
        "depends_on",
        "when",
        "parallel",
        "foreach",
        "retry",
        "on_failure",
        "checkpoint",
        "budget",
        "source",
        "required",
        "default",
        "continue",
        "skip_dependents",
        "abort",
        "enum",
        "array",
        "object",
        "agent",
        "operator",
        "static",
        "target",
        "true",
        "false",
        "null",
    }
)

# Field reference pattern: {{steps.X.Y...}}, {{inputs.X}}, {{target}}
_FIELD_REF_RE = re.compile(
    r"{{\s*(steps|inputs|target)\s*"
    r"((?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*}}"
)

_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Token:
    """One lexical token with source position for error reporting."""

    type: str
    value: str | int | float | bool | None
    line: int
    col: int


class TokenError(ValueError):
    """Raised when the DSL text cannot be tokenized."""


def tokenize(text: str) -> list[Token]:
    """Convert DSL source text into a list of :class:`Token` (EOF appended)."""
    tokens: list[Token] = []
    line = 1
    col = 1
    pos = 0
    n = len(text)

    while pos < n:
        ch = text[pos]

        # ── Whitespace / newlines ─────────────────────────────────────────
        if ch in " \t\r":
            col += 1
            pos += 1
            continue
        if ch == "\n":
            line += 1
            col = 1
            pos += 1
            continue

        # ── Field reference {{...}} ──────────────────────────────────────
        if text.startswith("{{", pos):
            m = _FIELD_REF_RE.match(text, pos)
            if not m:
                raise TokenError(
                    f"malformed field reference at line {line}, col {col}: "
                    "expected {{steps.X}}, {{inputs.X}}, or {{target}}"
                )
            kind = m.group(1)
            path = m.group(2)  # ".field1.field2" or ""
            tokens.append(Token(FIELD_REF, (kind, path), line, col))
            col += len(m.group(0))
            pos = m.end()
            continue

        # ── String literal ───────────────────────────────────────────────
        if ch == '"':
            m = _STRING_RE.match(text, pos)
            if not m:
                raise TokenError(f"unterminated string at line {line}, col {col}")
            raw = m.group(0)
            value = raw[1:-1]  # strip quotes
            # Handle escapes minimally
            value = value.replace('\\"', '"').replace("\\\\", "\\")
            tokens.append(Token(STRING, value, line, col))
            col += len(raw)
            pos = m.end()
            continue

        # ── Punctuation ──────────────────────────────────────────────────
        if ch in _PUNCT:
            tokens.append(Token(_PUNCT[ch], ch, line, col))
            col += 1
            pos += 1
            continue

        # ── Multi-char operators first ───────────────────────────────────
        matched = False
        for op_len in (2, 1):
            candidate = text[pos : pos + op_len]
            if candidate in _OPERATORS:
                tokens.append(Token(_OPERATORS[candidate], candidate, line, col))
                col += op_len
                pos += op_len
                matched = True
                break
        if matched:
            continue

        # ── Number ───────────────────────────────────────────────────────
        m = _NUMBER_RE.match(text, pos)
        if m:
            raw = m.group(0)
            if "." in raw:
                tokens.append(Token(FLOAT, float(raw), line, col))
            else:
                tokens.append(Token(INTEGER, int(raw), line, col))
            col += len(raw)
            pos += len(raw)
            continue

        # ── Identifier / keyword / bool / null ───────────────────────────
        m = _IDENT_RE.match(text, pos)
        if m:
            word = m.group(0)
            if word == "true":
                tokens.append(Token(BOOL, True, line, col))
            elif word == "false":
                tokens.append(Token(BOOL, False, line, col))
            elif word == "null":
                tokens.append(Token(NULL, None, line, col))
            else:
                tokens.append(Token(IDENTIFIER, word, line, col))
            col += len(word)
            pos += len(word)
            continue

        raise TokenError(f"unexpected character {ch!r} at line {line}, col {col}")

    tokens.append(Token(EOF, None, line, col))
    return tokens


__all__ = [
    "BOOL",
    "COLON",
    "COMMA",
    "DOT",
    "EOF",
    "EQ",
    "FIELD_REF",
    "FLOAT",
    "GE",
    "GT",
    "IDENTIFIER",
    "INTEGER",
    "LBRACE",
    "LBRACKET",
    "LE",
    "LT",
    "NE",
    "NULL",
    "RBRACE",
    "RBRACKET",
    "STRING",
    "Token",
    "TokenError",
    "tokenize",
]
