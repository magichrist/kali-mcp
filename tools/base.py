"""BaseTool abstract class — every native tool inherits this."""

from __future__ import annotations

import abc
import json
import logging
from typing import Any

from models import ToolError
from responses import error_response

logger = logging.getLogger("kali_mcp.tools")


class BaseTool(abc.ABC):
    """All native tools implement this interface."""

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @property
    @abc.abstractmethod
    def description(self) -> str: ...

    @property
    def default_timeout(self) -> int:
        return 300

    @abc.abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """Return JSON Schema for tool input parameters."""
        ...

    @abc.abstractmethod
    def validate(self, arguments: dict[str, Any]) -> None:
        """Raise ValueError if arguments are invalid."""
        ...

    @abc.abstractmethod
    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        """Build the command argument list (no shell)."""
        ...

    @abc.abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool and return MCP-formatted result."""
        ...

    async def safe_execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Safety net wrapper — catches ALL exceptions from execute().

        No tool should ever propagate an unhandled exception.
        This is the last line of defense.

        After execution, best-effort records the run to SQLite (scans + a
        generic findings row) and deposits the result JSON in the vault so
        other agents can discover it. Tools wanting per-finding/credential
        persistence call tools.persist.persist_run() themselves with parsed
        results; the central hook skips persistence when the tool already
        recorded the run (checked via the `_persisted` flag tools set).
        """
        try:
            result = await self.execute(arguments)
        except Exception as e:
            logger.exception("CRITICAL: unhandled exception in tool %s", self.name)
            return error_response(
                ToolError(
                    error=f"Internal error in {self.name}",
                    details=f"{type(e).__name__}: {e}",
                )
            )
        # Central persistence (best-effort, never breaks the tool response)
        if not getattr(self, "_persisted", False):
            try:
                self._central_persist(arguments, result)
            except Exception:  # noqa: BLE001 — persistence must never break execution
                logger.debug("central persistence failed for %s", self.name)
        return result

    def _central_persist(self, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        """Extract the ExecutionResult payload and persist scan + vault entry."""
        from tools.persist import persist_run

        data: dict[str, Any] | None = None
        try:
            text = result["content"][0]["text"]
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "stdout" in parsed:
                data = parsed
        except Exception:  # noqa: BLE001 — non-JSON responses are skipped
            data = None

        # Orchestrator tools manage their own state — don't double-record
        if getattr(self, "_skip_central_persist", False):
            return

        command = data.get("command", "") if data else ""
        persist_run(self.name, arguments, command, data)
