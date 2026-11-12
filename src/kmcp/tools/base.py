"""BaseTool abstract class — every native tool inherits this."""

from __future__ import annotations

import abc
import json
import logging
import re
import shutil
from typing import Any

from kmcp.models import ToolError
from kmcp.responses import error_response

logger = logging.getLogger("kmcp.tools")


def _camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case (e.g. scanType → scan_type)."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _coerce_value(value: Any, expected_type: str | None = None) -> Any:
    """Coerce common agent type mistakes to the *declared schema type*.

    Coercion respects the field's declared JSON-schema type — legit string
    values are never silently converted:

    - None            → "" for string fields; dropped (by the caller) otherwise
    - "300" (str)     → int 300  **only** when the field is integer-typed
    - "true"/"false"  → bool     **only** when the field is boolean-typed
    - list → comma-joined str **only** when the field is string-typed
    - dict → JSON str **only** when the field is string-typed
    - Already-correct types pass through unchanged.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        low = stripped.lower()
        if expected_type == "integer":
            try:
                return int(stripped)
            except ValueError:
                pass
            try:
                as_float = float(stripped)
            except ValueError:
                return stripped
            return int(as_float) if as_float.is_integer() else stripped
        if expected_type == "number":
            try:
                return float(stripped)
            except ValueError:
                return stripped
        if expected_type == "boolean":
            if low in ("true", "false"):
                return low == "true"
            if low in ("1", "0"):
                return low == "1"
            return stripped
        # string-typed (or undeclared) — keep the text verbatim; never
        # silently convert "true"/"300"/"0" to bool/int and corrupt data.
        return stripped
    if isinstance(value, list):
        # Only convert arrays to comma-separated strings when the schema
        # expects a string type. Array-typed fields pass through unchanged.
        if expected_type == "string":
            return ",".join(str(v) for v in value)
        return value
    if isinstance(value, dict):
        # Only convert dicts to JSON strings when the schema expects a string.
        # Object-typed fields pass through unchanged.
        if expected_type == "string":
            return json.dumps(value)
        return value
    return value


def _normalize_arguments(
    arguments: dict[str, Any], schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Normalize raw agent arguments to be forgiving of common mistakes.

    1. camelCase keys → snake_case (scanType → scan_type, inputFile → input_file)
    2. Type coercion *respecting the declared schema type*: "300" → 300 for
       integer fields, "true" → True for boolean fields; legit strings are
       never silently converted
    3. Strips whitespace from string values
    4. Drops null values for non-string fields so schema defaults apply
    5. Ignores unknown keys (never rejects extra properties)
    """
    if not arguments:
        return {}

    properties = (schema or {}).get("properties", {})
    normalized: dict[str, Any] = {}

    for key, value in arguments.items():
        # Normalize key: camelCase → snake_case, then use as-is if not in schema
        snake_key = _camel_to_snake(key)
        final_key = snake_key if snake_key in properties else key

        # Coerce value based on expected type from schema
        expected = None
        if final_key in properties:
            prop_type = properties[final_key].get("type")
            if isinstance(prop_type, list):
                expected = prop_type[0] if prop_type else None
            else:
                expected = prop_type

        # null on a non-string field means "use the default" — drop the key
        # so `arguments.get(field, default)` in the tool picks the default.
        if value is None and expected not in (None, "string"):
            continue

        normalized[final_key] = _coerce_value(value, expected)

    return normalized


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

    @property
    def binary(self) -> str:
        """Return the binary name this tool wraps, for existence checks.

        Defaults to the tool name. Override when the binary name differs
        (e.g. httpx wraps /usr/bin/httpx-toolkit).
        """
        return self.name

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

        Before execution, arguments are normalized to forgive common agent
        mistakes: camelCase keys, string booleans/integers, null values, and
        arrays passed where strings are expected.

        After execution, best-effort records the run to SQLite (scans + a
        generic findings row) and deposits the result JSON in the vault so
        other agents can discover it. Tools wanting per-finding/credential
        persistence call tools.persist.persist_run() themselves with parsed
        results; the central hook skips persistence when the tool already
        recorded the run (checked via the `_persisted` flag tools set).
        """
        # Normalize arguments to forgive common agent mistakes.
        normalized = _normalize_arguments(arguments, self.input_schema())

        # Binary existence check — warn when the wrapped binary is missing.
        # The execution engine already surfaces a clean "Binary not found"
        # error via its FileNotFoundError path, so here we only log so that
        # orchestration/utility tools (which wrap no binary) are not broken.
        binary = shutil.which(self.binary)
        if binary is None:
            logger.warning(
                "Tool '%s' wraps binary '%s' which was not found in PATH; "
                "execution will return a binary-not-found error at runtime.",
                self.name,
                self.binary,
            )
        try:
            result = await self.execute(normalized)
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
                self._central_persist(normalized, result)
            except Exception:  # noqa: BLE001 — persistence must never break execution
                logger.debug("central persistence failed for %s", self.name)
        return result

    def _central_persist(
        self,
        arguments: dict[str, Any],
        result: dict[str, Any],
        assessment_id: str | None = None,
        job_id: str | None = None,
    ) -> None:
        """Extract the ExecutionResult payload and persist scan + vault entry."""
        from kmcp.tools.persist import persist_run

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
        persist_run(
            self.name,
            arguments,
            command,
            data,
            assessment_id=assessment_id,
            job_id=job_id,
        )
