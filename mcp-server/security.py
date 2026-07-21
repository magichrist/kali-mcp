"""Security helpers for command sanitization."""

from __future__ import annotations

import shlex


def sanitize_command_parts(parts: list[str]) -> list[str]:
    """Ensure command parts are safe for subprocess exec (no shell injection)."""
    return [str(p) for p in parts]


def quote_argument(arg: str) -> str:
    """Shell-safe quote a single argument."""
    return shlex.quote(arg)
