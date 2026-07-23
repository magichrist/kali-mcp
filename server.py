"""MCP Server — SSE transport, tool registration, request handling."""

from __future__ import annotations

import json
import logging
import sys
import os
from contextlib import asynccontextmanager

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool as MCPTool
from mcp.server.fastmcp.utilities.func_metadata import func_metadata

from config import config
from registry import registry
from responses import success_response, error_response_from_exception
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
    port=config.port,
)


# Register all tools — create MCPTool with input_schema so the agent receives
# full parameter schemas instead of having to guess.
for tool_instance in ALL_TOOLS:
    registry.register(tool_instance)

    def _make_handler(t):
        async def handler(**kwargs) -> str:
            try:
                logger.info("tool=%s args=%s", t.name, list(kwargs.keys()))
                result = await t.execute(kwargs)
                # result is {"content": [...], "isError": bool} — extract the text
                # so FastMCP re-wraps it in a single TextContent without double-encoding.
                if isinstance(result, dict) and "content" in result:
                    for block in result["content"]:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return block["text"]
                return json.dumps(result, indent=2)
            except Exception as e:
                logger.exception("Unhandled error in tool %s", t.name)
                return json.dumps({"error": str(e)}, indent=2)

        handler.__name__ = t.name
        handler.__doc__ = t.description
        return handler

    tool_fn = _make_handler(tool_instance)

    # Build MCPTool directly with the tool's input_schema so the agent
    # receives the full JSON Schema for parameters.
    fm = func_metadata(tool_fn)
    mcp_tool = MCPTool(
        fn=tool_fn,
        name=tool_instance.name,
        description=tool_instance.description,
        parameters=tool_instance.input_schema(),
        fn_metadata=fm,
        is_async=True,
    )
    mcp._tool_manager._tools[tool_instance.name] = mcp_tool


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


class TokenAuthMiddleware:
    """Check Bearer token or ?token= query param against configured API token."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.token:
            from starlette.requests import Request
            from starlette.responses import JSONResponse

            request = Request(scope, receive)
            auth = request.headers.get("authorization", "")
            query_token = request.query_params.get("token", "")
            provided = auth.removeprefix("Bearer ").strip() or query_token
            if provided != self.token:
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


if __name__ == "__main__":
    import uvicorn
    from starlette.middleware.cors import CORSMiddleware

    logger.info(
        "Starting %s v%s on %s:%d",
        config.server_name,
        config.server_version,
        config.host,
        config.port,
    )

    if config.transport == "streamable-http":
        app = mcp.streamable_http_app()
        logger.info("Transport: streamable-http")
    else:
        app = mcp.sse_app()
        logger.info("Transport: sse")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_token = os.getenv("MCP_API_TOKEN", "")
    if api_token:
        app.add_middleware(TokenAuthMiddleware, token=api_token)
        logger.info("API token authentication enabled")
    else:
        logger.warning("No MCP_API_TOKEN set — server is open. Set MCP_API_TOKEN in .env for production.")

    uvicorn.run(app, host=config.host, port=config.port)
