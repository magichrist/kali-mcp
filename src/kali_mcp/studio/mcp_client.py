"""External MCP client for Playbook Studio (Phase 3, Task B).

Purpose-built client for connecting to *external* MCP servers, discovering
their tools, importing their schemas, and proxying execution. Per TD-11,
external MCP tools are **untrusted by default**:

- Discovery → schema import → proxied execution
- Timeouts on every call
- Redaction of secrets in results
- Imported tools default to ``internal`` visibility (never auto-exposed to agents)

Transports supported: stdio, SSE, streamable-HTTP (via the ``mcp`` package
client primitives already used by the server).

This client never mutates the local registry directly — callers decide whether
and how to import discovered tools (see ``studio/service_tools.py``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.stdio import stdio_client

logger = logging.getLogger("kali_mcp.studio.mcp_client")

#: Default timeout (seconds) for external MCP calls.
DEFAULT_TIMEOUT = 30

#: Secret-like patterns redacted from tool results (cross-cutting with
#: studio/redaction.py in Phase 4).
_SECRET_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9+/]{20,}={0,2}"),  # base64-ish tokens
    re.compile(r"\b(sk|pk|ghp|xoxb|xoxp|glpat|sk_live|sk_test)_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\b[A-Fa-f0-9]{32,64}\b"),  # hex digests / keys
    re.compile(r"\b(password|secret|token|api_key|apikey|private_key)\b\s*[:=]\s*\S+", re.I),
]


class MCPClientError(Exception):
    """Raised when an external MCP operation fails."""


class ExternalMCPClient:
    """Client for a single external MCP server connection.

    Usage::

        async with ExternalMCPClient("stdio", command=["npx", "mcp-server-fs"]) as client:
            await client.connect()
            tools = await client.list_tools()
            result = await client.call_tool("read_file", {"path": "/etc/hostname"})
    """

    def __init__(
        self,
        transport: str,
        *,
        url: str | None = None,
        command: list[str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        headers: dict[str, str] | None = None,
    ):
        """Create a client for an external MCP server.

        Args:
            transport: ``stdio``, ``sse``, or ``streamable-http``.
            url: Server URL (required for sse / streamable-http).
            command: Command + args (required for stdio).
            timeout: Per-call timeout in seconds.
            headers: Extra HTTP headers (sse / streamable-http only).
        """
        if transport not in {"stdio", "sse", "streamable-http"}:
            raise MCPClientError(
                f"unsupported transport {transport!r}; expected stdio/sse/streamable-http"
            )
        if transport in {"sse", "streamable-http"} and not url:
            raise MCPClientError(f"{transport} requires a url")
        if transport == "stdio" and not command:
            raise MCPClientError("stdio requires a command")

        self.transport = transport
        self.url = url
        self.command = command
        self.timeout = timeout
        self.headers = headers or {}

        self._session: ClientSession | None = None
        self._cleanup: Any = None
        self._connected = False

    # ── context manager ──────────────────────────────────────────────────

    async def __aenter__(self) -> "ExternalMCPClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()

    # ── connect / disconnect ─────────────────────────────────────────────

    async def connect(self) -> None:
        """Open the transport and initialize the MCP session."""
        if self._connected:
            return

        try:
            if self.transport == "stdio":
                if self.command is None:
                    raise MCPClientError("stdio requires a command")
                read, write, cleanup = stdio_client(command=self.command)
            elif self.transport == "sse":
                if self.url is None:
                    raise MCPClientError("sse requires a url")
                read, write, cleanup = sse_client(url=self.url, headers=self.headers)
            else:  # streamable-http
                if self.url is None:
                    raise MCPClientError("streamable-http requires a url")
                read, write, cleanup = streamablehttp_client(
                    url=self.url, headers=self.headers
                )

            self._cleanup = cleanup
            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
            self._connected = True
            logger.info(
                "Connected to external MCP server (transport=%s)", self.transport
            )
        except Exception as exc:  # noqa: BLE001 — wrap into MCPClientError
            await self.disconnect()
            raise MCPClientError(f"failed to connect: {exc}") from exc

    async def disconnect(self) -> None:
        """Close the session and transport."""
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 — disconnect must not raise
                logger.debug("session close raised, ignoring")
            self._session = None
        if self._cleanup is not None:
            try:
                await self._cleanup.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                logger.debug("cleanup raised, ignoring")
            self._cleanup = None
        self._connected = False

    # ── discovery ────────────────────────────────────────────────────────

    async def list_tools(self) -> list[dict[str, Any]]:
        """List tools exposed by the external server.

        Returns a list of tool dicts with ``name``, ``description``, and
        ``inputSchema`` keys (MCP protocol format).
        """
        if not self._connected or self._session is None:
            raise MCPClientError("not connected")

        try:
            result = await asyncio.wait_for(
                self._session.list_tools(), timeout=self.timeout
            )
        except asyncio.TimeoutError as exc:
            raise MCPClientError("list_tools timed out") from exc
        except Exception as exc:  # noqa: BLE001
            raise MCPClientError(f"list_tools failed: {exc}") from exc

        tools: list[dict[str, Any]] = []
        for t in getattr(result, "tools", []):
            tools.append(
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema or {},
                }
            )
        return tools

    # ── execution ────────────────────────────────────────────────────────

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a tool on the external server and return a redacted result.

        The result is passed through :func:`redact_result` before returning,
        so secrets never leave this module unredacted.
        """
        if not self._connected or self._session is None:
            raise MCPClientError("not connected")

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments), timeout=self.timeout
            )
        except asyncio.TimeoutError as exc:
            raise MCPClientError(f"call_tool {name} timed out") from exc
        except Exception as exc:  # noqa: BLE001
            raise MCPClientError(f"call_tool {name} failed: {exc}") from exc

        # Normalize MCP result into a dict
        raw: Any
        if hasattr(result, "model_dump"):
            raw = result.model_dump()
        elif hasattr(result, "dict"):
            raw = result.dict()
        elif isinstance(result, dict):
            raw = result
        else:
            raw = {"content": str(result)}

        return redact_result(raw)


def redact_result(result: dict[str, Any]) -> dict[str, Any]:
    """Redact secret-like values from a tool result dict (recursive).

    Mirrors the planned studio/redaction.py (Phase 4) so secrets are stripped
    at every egress point. Imported external tool results pass through here
    before reaching agents or API responses.
    """
    if not isinstance(result, dict):
        return result

    redacted: dict[str, Any] = {}
    for key, value in result.items():
        key_lower = str(key).lower()
        is_secret_key = any(
            kw in key_lower for kw in ("secret", "token", "password", "api_key", "apikey", "private_key", "credential")
        )
        if is_secret_key and isinstance(value, (str, int, float, bool)):
            redacted[key] = "***REDACTED***"
        elif isinstance(value, dict):
            redacted[key] = redact_result(value)
        elif isinstance(value, list):
            redacted[key] = [redact_result(v) if isinstance(v, dict) else v for v in value]
        elif isinstance(value, str):
            redacted[key] = _redact_string(value)
        else:
            redacted[key] = value
    return redacted


def _redact_string(text: str) -> str:
    """Redact secret-like patterns inside a string."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("***REDACTED***", text)
    return text


__all__ = [
    "ExternalMCPClient",
    "MCPClientError",
    "redact_result",
    "DEFAULT_TIMEOUT",
]
