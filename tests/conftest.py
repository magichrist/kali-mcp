"""Shared pytest configuration for kali-mcp tests.

Registers all tools into the global registry, mirroring server.py's startup
wiring, so integration tests can resolve tools via the registry.
"""

from __future__ import annotations

from kali_mcp.registry import registry
from kali_mcp.tools import ALL_TOOLS


def _register_all_tools() -> None:
    """Populate the global tool registry, mirroring server.py's startup wiring.

    Integration tests (playbook engine, parallel_execute) resolve tools via the
    global registry, which is normally populated only when server.py runs.
    """
    for tool in ALL_TOOLS:
        registry.register(tool)


_register_all_tools()
