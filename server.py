"""MCP Server — SSE transport, tool registration, request handling."""

from __future__ import annotations

import json
import logging
import signal
import sys
import os
import inspect
import uuid
from typing import Optional
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

    # Verify critical binaries exist at startup
    import shutil
    critical_bins = ["nmap", "curl"]
    for bin_name in critical_bins:
        if shutil.which(bin_name):
            logger.info("Startup check OK: %s found", bin_name)
        else:
            logger.warning("Startup check WARN: %s not found in PATH", bin_name)

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
        schema = t.input_schema()
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        params = []
        for name, prop in properties.items():
            has_default = "default" in prop
            default = prop.get("default") if has_default else inspect.Parameter.empty
            annotation = str if name not in required else str
            if has_default:
                params.append(inspect.Parameter(
                    name, inspect.Parameter.KEYWORD_ONLY,
                    default=default, annotation=annotation,
                ))
            else:
                params.append(inspect.Parameter(
                    name, inspect.Parameter.KEYWORD_ONLY,
                    annotation=annotation,
                ))

        sig = inspect.Signature(params)

        async def handler(**kwargs) -> str:
            request_id = uuid.uuid4().hex[:12]
            try:
                logger.info("request=%s tool=%s args=%s", request_id, t.name, list(kwargs.keys()))
                result = await t.safe_execute(kwargs)
                if isinstance(result, dict) and "content" in result:
                    for block in result["content"]:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return block["text"]
                return json.dumps(result, indent=2)
            except asyncio.CancelledError:
                logger.warning("request=%s tool=%s request cancelled by client", request_id, t.name)
                return json.dumps({"error": "Request cancelled"})
            except Exception as e:
                logger.exception("request=%s catastrophic error in tool %s", request_id, t.name)
                return json.dumps({"error": "Tool execution failed"}, indent=2)

        handler.__name__ = t.name
        handler.__doc__ = t.description
        handler.__signature__ = sig
        return handler

    tool_fn = _make_handler(tool_instance)

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

    if config.transport == "streamable-http":
        app = mcp.streamable_http_app()
        logger.info("Transport: streamable-http")
    else:
        app = mcp.sse_app()
        logger.info("Transport: sse")

    origins = [o.strip() for o in config.allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_token = os.getenv("MCP_API_TOKEN", "")
    if api_token:
        app.add_middleware(TokenAuthMiddleware, token=api_token)
        logger.info("API token authentication enabled")
    else:
        logger.warning("No MCP_API_TOKEN set — server is open. Set MCP_API_TOKEN in .env for production.")

    # Graceful shutdown on SIGTERM/SIGINT
    def _shutdown_handler(signum, frame):
        logger.info("Received signal %d, shutting down gracefully...", signum)

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    uvicorn.run(app, host=config.host, port=config.port)
