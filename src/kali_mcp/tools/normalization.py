"""Normalization mixin for per-tool output parsing.

This provides a base interface for tools to implement tool-specific
parsing/normalization. The MCP wrappers should call `normalize()` and
embed the result under stdout as a structured JSON payload.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class NormalizedToolMixin(ABC):
    @abstractmethod
    def normalize(
        self, stdout: str, stderr: str, exit_code: int, **kwargs: Any
    ) -> dict[str, Any]:
        """Return a dict containing at least 'raw', 'normalized', and parse metadata."""
        raise NotImplementedError
