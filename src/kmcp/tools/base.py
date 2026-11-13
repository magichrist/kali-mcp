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
    def aliases(self) -> tuple[str, ...]:
        """Alternate tool names agents commonly guess ("search", "scan", ...).

        Registered in the registry and as real MCP tools so guesses resolve
        instead of erroring. Override per tool; default: no aliases.
        """
        return ()

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
        if binary is None and not getattr(self, "_skip_binary_check", False):
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
        # Friendlier validation errors: enrich "Validation error" responses
        # with usage hints (required fields + omit-to-use-default notes) so
        # agents can self-correct in one retry instead of several.
        if isinstance(result, dict) and result.get("isError"):
            try:
                result = self._augment_validation_error(normalized, result)
            except Exception:  # noqa: BLE001 — hints must never break the response
                logger.debug("validation hint augmentation failed for %s", self.name)
        # Central persistence (best-effort, never breaks the tool response)
        if not getattr(self, "_persisted", False):
            try:
                self._central_persist(normalized, result)
            except Exception:  # noqa: BLE001 — persistence must never break execution
                logger.debug("central persistence failed for %s", self.name)
        return result

    # ── Validation-error enrichment (friendlier agent self-correction) ────

    def _example_arguments(self, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build an example arguments dict from a tool's input schema.

        Required fields get a placeholder value guessed from the field name
        and type; optional fields with defaults are shown with their default.
        Defaults to this tool's own schema.
        """
        schema = schema if schema is not None else self.input_schema()
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        example: dict[str, Any] = {}

        for name, prop in properties.items():
            ptype = prop.get("type", "string")
            if isinstance(ptype, list):
                ptype = ptype[0]
            if name in required:
                lname = name.lower()
                desc = str(prop.get("description", "")).lower()
                if "url" in lname or "url" in desc:
                    example[name] = "http://example.com"
                elif "target" in lname or "host" in lname or "ip" in lname:
                    example[name] = "192.168.1.1"
                elif "domain" in lname:
                    example[name] = "example.com"
                elif "path" in lname or "file" in lname:
                    example[name] = "/etc/hostname"
                elif "command" in lname:
                    example[name] = "whoami"
                elif "code" in lname:
                    example[name] = "print('hello')"
                elif "query" in lname or "search" in lname:
                    example[name] = "apache"
                elif ptype == "object":
                    example[name] = {"key": "value"}
                elif ptype == "array":
                    example[name] = ["item1", "item2"]
                elif ptype == "integer":
                    example[name] = 1
                else:
                    example[name] = f"<{name}>"
            elif "default" in prop:
                example[name] = prop["default"]
        return example

    def _validation_hints(self) -> str:
        """Build a usage-hints string from the tool's input schema."""
        schema = self.input_schema()
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        parts: list[str] = []
        for name in required:
            prop = properties.get(name, {})
            desc = str(prop.get("description", "")).strip()
            parts.append(f"'{name}': {desc}" if desc else f"'{name}' is required")
        for name, prop in properties.items():
            if name in required:
                continue
            if "default" in prop:
                parts.append(
                    f"omit '{name}' to use default {prop['default']!r}"
                )
        return "; ".join(parts)

    def _augment_validation_error(
        self, arguments: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        """Enrich a Validation error response with usage hints + an example.

        Tools return ``error_response(ToolError(error="Validation error",
        details=...))`` on bad arguments. This appends required-field hints
        and an example call so the agent can self-correct immediately.
        """
        if not result.get("content"):
            return result
        block = result["content"][0]
        text = block.get("text") if isinstance(block, dict) else None
        payload: dict[str, Any]
        if isinstance(text, str):
            payload = json.loads(text)
        elif isinstance(text, dict):
            payload = text
        else:
            return result
        if payload.get("error") != "Validation error":
            return result

        hints = self._validation_hints()
        details = str(payload.get("details", "")).rstrip(". ")
        payload["details"] = f"{details}. Required usage: {hints}." if hints else details
        payload["example_arguments"] = self._example_arguments()
        block["text"] = json.dumps(payload, indent=2)
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
