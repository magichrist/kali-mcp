"""Shared helpers for internal workflow modules.

These helpers keep module handlers thin: validate declared inputs, look up a
native tool from the :class:`~kali_mcp.registry.ToolRegistry` (or an injected
lookup for tests), call its public ``safe_execute``/``execute`` path, and
normalize the MCP response envelope into plain execution data.

No helper shells out directly and no helper performs network I/O on its own.
"""

from __future__ import annotations

import inspect
import ipaddress
import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("kali_mcp.playbooks.modules")

__all__ = [
    "call_tool",
    "extract_hostnames",
    "extract_ip_literals",
    "findings_of",
    "first_available_tool",
    "is_ip",
    "lookup_tool",
    "normalized_of",
    "parse_http_lines",
    "parse_open_ports",
    "require_input",
    "require_list",
    "require_text",
    "stdout_of",
    "unwrap_tool_response",
]

# ── input validation ────────────────────────────────────────────────────


def require_input(inputs: dict[str, Any], key: str, expected: type | None = None) -> Any:
    """Return a required input value, raising ``ValueError`` when missing."""
    if key not in inputs or inputs[key] is None:
        raise ValueError(f"Missing required input: {key}")
    value = inputs[key]
    if expected is not None and not isinstance(value, expected):
        raise ValueError(
            f"Input '{key}' must be {expected.__name__}, got {type(value).__name__}"
        )
    return value


def require_text(inputs: dict[str, Any], key: str) -> str:
    """Return a required non-empty string input."""
    value = require_input(inputs, key, str).strip()
    if not value:
        raise ValueError(f"Input '{key}' must not be empty")
    return value


def require_list(inputs: dict[str, Any], key: str, item_type: type | None = None) -> list[Any]:
    """Return a required list input, optionally checking item types."""
    value = require_input(inputs, key, list)
    if item_type is not None:
        for item in value:
            if not isinstance(item, item_type):
                raise ValueError(
                    f"Input '{key}' items must be {item_type.__name__}, got "
                    f"{type(item).__name__}"
                )
    return value


# ── tool lookup + invocation ────────────────────────────────────────────

ToolLookup = Any


def lookup_tool(name: str, lookup: ToolLookup = None) -> Any | None:
    """Resolve a native tool instance.

    ``lookup`` may be ``None`` (lazy real registry), a callable
    ``name -> tool | None``, or a mapping of names to injected fake tools.
    """
    if lookup is None:
        from kali_mcp.registry import registry

        return registry.get(name)
    if callable(lookup):
        return lookup(name)
    if isinstance(lookup, Mapping):
        return lookup.get(name)
    raise TypeError("_tool_lookup must be None, a callable, or a mapping")


def first_available_tool(
    candidates: Sequence[str], lookup: ToolLookup = None
) -> tuple[str, Any] | None:
    """Return the first registered ``(name, tool)`` from ``candidates``."""
    for name in candidates:
        tool = lookup_tool(name, lookup)
        if tool is not None:
            return name, tool
    return None


async def call_tool(tool: Any, arguments: dict[str, Any]) -> Any:
    """Call a native tool through its public execution path.

    Prefers ``safe_execute`` (the exception-catching public wrapper used by
    the DAG engine) and falls back to ``execute`` for lightweight tools or
    test fakes. Awaitable results are awaited.
    """
    safe_execute = getattr(tool, "safe_execute", None)
    execute = getattr(tool, "execute", None)
    runner = safe_execute if callable(safe_execute) else execute
    if not callable(runner):
        raise TypeError(f"Tool {tool!r} exposes neither safe_execute() nor execute()")
    result = runner(arguments)
    if inspect.isawaitable(result):
        result = await result
    return result


# ── MCP response normalization ──────────────────────────────────────────


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _unwrap_persistence_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Unwrap ``{raw, findings, normalized}`` envelopes produced by persist.py."""
    raw = data.get("raw")
    if isinstance(raw, dict):
        merged = dict(raw)
        merged.setdefault("findings", data.get("findings") or [])
        merged.setdefault("normalized", data.get("normalized") or {})
        return merged
    return data


def unwrap_tool_response(response: Any) -> dict[str, Any]:
    """Return the execution-result dict inside an MCP tool response.

    Handles the standard ``{"content": [{"text": ...}]}`` envelope, nested
    persistence payloads whose ``stdout`` is itself JSON, and plain dicts
    returned by fakes. Non-dict responses yield an empty dict.
    """
    if not isinstance(response, dict):
        return {}

    data: Any = response
    content = data.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        text = first.get("text") if isinstance(first, dict) else None
        if isinstance(text, str):
            parsed = _loads(text)
            if isinstance(parsed, dict):
                data = parsed
            else:
                return {"stdout": text, "success": not bool(data.get("isError"))}

    if not isinstance(data, dict):
        return {}

    data = _unwrap_persistence_payload(data)

    stdout = data.get("stdout")
    if isinstance(stdout, str) and stdout.strip().startswith(("{", "[")):
        inner = _loads(stdout)
        if isinstance(inner, dict):
            data = _unwrap_persistence_payload(inner)
    return data


def stdout_of(response: Any) -> str:
    """Extract raw stdout text from an MCP tool response."""
    stdout = unwrap_tool_response(response).get("stdout")
    return stdout if isinstance(stdout, str) else ""


def findings_of(response: Any) -> list[dict[str, Any]]:
    """Extract structured findings from a tool response, if present."""
    findings = unwrap_tool_response(response).get("findings")
    if isinstance(findings, list):
        return [item for item in findings if isinstance(item, dict)]
    return []


def normalized_of(response: Any) -> dict[str, Any]:
    """Extract the normalized payload from a tool response, if present."""
    normalized = unwrap_tool_response(response).get("normalized")
    return normalized if isinstance(normalized, dict) else {}


# ── parsing helpers (pure, no network) ──────────────────────────────────

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,63}\.?$"
)
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_NMAP_OPEN_RE = re.compile(
    r"(?m)^\s*(?:[|*]\s*)?(\d{1,5})/(tcp|udp)\s+open(?:\s+(\S+))?"
)
_MASSCAN_OPEN_RE = re.compile(
    r"Discovered open port\s+(\d{1,5})/(tcp|udp)\s+on\s+([\w.:-]+)", re.IGNORECASE
)

_TOKEN_SPLIT_RE = re.compile(r"[\s,;|'\"()\[\]{}<>]+")


def is_ip(value: str) -> bool:
    """Return True when ``value`` is a valid IPv4/IPv6 literal."""
    try:
        ipaddress.ip_address(value.strip())
        return True
    except ValueError:
        return False


def extract_ip_literals(text: str) -> list[str]:
    """Extract unique IP literals from arbitrary text, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _IPV4_RE.finditer(text or ""):
        candidate = match.group(0)
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    for token in _TOKEN_SPLIT_RE.split(text or ""):
        candidate = token.strip().rstrip(".")
        if ":" in candidate and is_ip(candidate) and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def extract_hostnames(text: str) -> list[str]:
    """Extract unique DNS hostnames from newline/token oriented tool output."""
    seen: set[str] = set()
    out: list[str] = []
    for token in _TOKEN_SPLIT_RE.split(text or ""):
        candidate = token.strip().strip("'\"")
        if not candidate or "://" in candidate:
            if "://" in candidate:
                host = urlparse(candidate).hostname
                if host:
                    candidate = host
            else:
                continue
        candidate = candidate.rstrip(".,;:")
        candidate = candidate.lower()
        if not candidate or is_ip(candidate):
            continue
        if _HOSTNAME_RE.match(candidate) and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def parse_open_ports(stdout: str) -> list[dict[str, Any]]:
    """Parse nmap/masscan stdout into ``{port, protocol, service}`` entries."""
    seen: set[tuple[int, str]] = set()
    ports: list[dict[str, Any]] = []
    for match in _NMAP_OPEN_RE.finditer(stdout or ""):
        port, protocol, service = match.groups()
        key = (int(port), protocol)
        if key in seen:
            continue
        seen.add(key)
        ports.append(
            {
                "port": int(port),
                "protocol": protocol,
                "service": service or "",
            }
        )
    for match in _MASSCAN_OPEN_RE.finditer(stdout or ""):
        port, protocol, _host = match.groups()
        key = (int(port), protocol)
        if key in seen:
            continue
        seen.add(key)
        ports.append({"port": int(port), "protocol": protocol, "service": ""})
    return ports


def parse_http_lines(stdout: str) -> list[dict[str, Any]]:
    """Parse httpx/whatweb stdout into HTTP service dicts."""
    services: list[dict[str, Any]] = []
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("{"):
            parsed = _loads(line)
            if isinstance(parsed, dict):
                url = parsed.get("url") or parsed.get("input") or parsed.get("host")
                if isinstance(url, str) and url:
                    tech = parsed.get("tech") or parsed.get("technologies") or []
                    if isinstance(tech, str):
                        tech = [tech]
                    services.append(
                        {
                            "url": url,
                            "status_code": parsed.get("status_code")
                            or parsed.get("status"),
                            "title": parsed.get("title") or "",
                            "tech": list(tech) if isinstance(tech, list) else [],
                        }
                    )
                    continue

        url_match = re.search(r"https?://[^\s\[\]]+", line)
        if not url_match:
            continue
        url = url_match.group(0).rstrip(",;")
        brackets = re.findall(r"\[([^\]]*)\]", line)
        status_match = re.search(r"\[(\d{3})(?:\s[^\]]*)?\]", line)
        status_code = int(status_match.group(1)) if status_match else None
        title = ""
        tech: list[str] = []
        for item in brackets:
            if status_code is not None and item.startswith(str(status_code)):
                continue
            if not title and not item.isdigit() and "[" not in item:
                title = item
            elif item:
                tech.append(item)
        services.append(
            {
                "url": url,
                "status_code": status_code,
                "title": title,
                "tech": tech,
            }
        )
    return services
