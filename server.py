"""MCP Server — SSE transport, tool registration, request handling."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import os
from contextlib import asynccontextmanager

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from config import config
from registry import registry
from models import ToolError
from responses import success_response, error_response, error_response_from_exception
from logging_utils import setup_logging

# Import all tools (triggers registration)
from tools import ALL_TOOLS

setup_logging()
logger = logging.getLogger("kali_mcp.server")


@asynccontextmanager
async def lifespan(app):
    """Server lifecycle — startup and shutdown."""
    logger.info("Server starting up...")
    logger.info("Registered %d tools: %s", len(ALL_TOOLS), [t.name for t in ALL_TOOLS])
    yield
    logger.info("Server shutting down...")


# Create FastMCP instance
mcp = FastMCP(
    name=config.server_name,
    instructions=(
        "Kali MCP Server — penetration testing execution backend. "
        "Exposes native security tools and a generic_command escape hatch. "
        "All tools return structured JSON with stdout, stderr, exit_code, and timing."
    ),
    lifespan=lifespan,
    host=config.host,
    port=config.port
)


# Register all tools with FastMCP
for tool_instance in ALL_TOOLS:
    registry.register(tool_instance)

    def _make_handler(t):
        async def handler(**kwargs) -> str:
            try:
                result = await t.execute(kwargs)
                logger.info("tool=%s args=%s", t.name, list(kwargs.keys()))
                return json.dumps(result, indent=2)
            except Exception as e:
                logger.exception("Unhandled error in tool %s", t.name)
                return json.dumps(error_response_from_exception(e), indent=2)
        handler.__name__ = t.name
        handler.__doc__ = t.description
        return handler

    tool_fn = _make_handler(tool_instance)
    mcp.add_tool(tool_fn, name=tool_instance.name, description=tool_instance.description)


# Health check tool
@mcp.tool()
def health_check() -> str:
    """Check server health and list available tools."""
    tools = registry.tool_names()
    return json.dumps({
        "status": "healthy",
        "server": config.server_name,
        "version": config.server_version,
        "available_tools": tools,
        "tool_count": len(tools),
    }, indent=2)


if __name__ == "__main__":
    logger.info(
        "Starting %s v%s on %s:%d",
        config.server_name,
        config.server_version,
        config.host,
        config.port,
    )
    mcp.run(transport="sse")
