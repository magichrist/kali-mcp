"""Kali-MCP Playbook Studio package.

Backend logic for the Studio (REST API + service layer). MCP routes are
mounted in `src/kali_mcp/server.py`. The Studio is optional — the CLI and MCP
server work without it (spec AC 19).
"""

from __future__ import annotations

from kali_mcp.studio.api import mount_studio_routes


def StudioAPI(app) -> None:
    """Mount Studio REST routes on the given Starlette app (router factory)."""
    mount_studio_routes(app)


__all__ = ["StudioAPI", "mount_studio_routes"]
