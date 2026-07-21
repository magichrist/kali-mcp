"""Standardized MCP response builders."""

from __future__ import annotations

import json
from typing import Any

from models import ExecutionResult, ToolError


def success_response(result: ExecutionResult) -> dict[str, Any]:
    """Build a successful tool result for MCP."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result.to_dict(), indent=2),
            }
        ],
        "isError": False,
    }


def error_response(error: ToolError) -> dict[str, Any]:
    """Build an error tool result for MCP."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(error.to_dict(), indent=2),
            }
        ],
        "isError": True,
    }


def error_response_from_exception(exc: Exception) -> dict[str, Any]:
    """Build error response from caught exception — never exposes traceback."""
    return error_response(ToolError(error=str(exc)))
