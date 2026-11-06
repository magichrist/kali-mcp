"""Redaction helpers for Playbook Studio (Phase 4).

Cross-cutting redaction applied at every egress point: API responses, logs,
step outputs, evidence, and MCP tool results. Secrets are stored as
references; actual values live in the credentials/vault systems. This module
ensures secrets never leave the server in plaintext.

Patterns cover common secret formats: API keys, tokens, passwords, base64-ish
strings, hex digests, and key=value secret assignments.
"""

from __future__ import annotations

import copy
import re
from typing import Any

# Secret-like key names (matched case-insensitively against dict keys)
_SECRET_KEYS = frozenset(
    {
        "secret",
        "token",
        "password",
        "passwd",
        "api_key",
        "apikey",
        "apikey",
        "private_key",
        "privatekey",
        "access_key",
        "accesskey",
        "secret_key",
        "secretkey",
        "client_secret",
        "clientsecret",
        "credential",
        "credentials",
        "auth",
        "authorization",
        "cookie",
        "session",
        "session_id",
        "sessionid",
        "refresh_token",
        "refreshtoken",
        "id_token",
        "idtoken",
    }
)

# Regex patterns for secret-like values inside strings
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(sk|pk|ghp|xoxb|xoxp|glpat|sk_live|sk_test)_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\b[A-Fa-f0-9]{32,64}\b"),  # hex digests / keys
    re.compile(
        r"\b(password|secret|token|api_key|apikey|private_key|access_key)\b\s*[:=]\s*\S+",
        re.I,
    ),
    re.compile(r"\b[A-Za-z0-9+/]{40,}\s*={0,2}\b"),  # base64-ish tokens
]


_REDACTED = "***REDACTED***"


def _is_secret_key(key: str) -> bool:
    """Return True if a dict key looks like it holds a secret."""
    kl = key.lower()
    return kl in _SECRET_KEYS or any(kw in kl for kw in _SECRET_KEYS)


def _redact_string(text: str) -> str:
    """Redact secret-like patterns inside a string."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def redact(value: Any) -> Any:
    """Recursively redact secret-like values from a data structure.

    - Dicts: keys matching ``_SECRET_KEYS`` are replaced with ``***REDACTED***``;
      values are recursively redacted.
    - Strings: secret-like patterns are replaced.
    - Lists/tuples: elements recursively redacted.
    - Everything else: returned unchanged.

    Safe to call on arbitrary JSON-serializable data.
    """
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, val in value.items():
            if _is_secret_key(str(key)):
                redacted[str(key)] = _REDACTED
            else:
                redacted[str(key)] = redact(val)
        return redacted
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v) for v in value)
    if isinstance(value, str):
        return _redact_string(value)
    return value


def redact_result(result: dict[str, Any]) -> dict[str, Any]:
    """Redact a tool result dict (alias for :func:`redact` for clarity)."""
    return redact(result)


def redact_log(message: str) -> str:
    """Redact secrets from a log message string."""
    return _redact_string(message)


def redact_step_outputs(outputs: Any) -> Any:
    """Redact step outputs before embedding in API responses or logs."""
    return redact(outputs)


__all__ = [
    "redact",
    "redact_result",
    "redact_log",
    "redact_step_outputs",
    "_REDACTED",
]
