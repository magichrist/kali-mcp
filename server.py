"""MCP Server — hardened SSE transport, tool registration, request handling."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import signal
import sys
import os
import inspect
import threading
import time
import uuid
from contextlib import asynccontextmanager

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool as MCPTool
from mcp.server.fastmcp.utilities.func_metadata import func_metadata

from config import config
from execution import engine
from registry import registry
from responses import success_response, error_response_from_exception
from logging_utils import setup_logging

# Import all tools (triggers registration)
from tools import ALL_TOOLS

setup_logging()
logger = logging.getLogger("kali_mcp.server")


# ── Health Monitor ──────────────────────────────────────────────
class HealthMonitor:
    """Background thread that monitors server health and cleans up stuck state."""

    def __init__(self) -> None:
        self._running = False
        self._last_gc = time.monotonic()
        self._request_count = 0
        self._error_count = 0
        self._start_time = time.monotonic()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True, name="health-monitor")
        t.start()
        logger.info("Health monitor started")

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            time.sleep(30)
            try:
                self._check()
            except Exception:
                pass  # Monitor must never crash

    def _check(self) -> None:
        now = time.monotonic()

        # Periodic GC (every 5 minutes)
        if now - self._last_gc > 300:
            gc.collect()
            self._last_gc = now

        # Check for stuck executions
        stuck = engine.get_stuck_executions()
        if stuck:
            for s in stuck:
                logger.warning(
                    "health: stuck execution detected — request=%s tool=%s elapsed=%.0fs",
                    s["request_id"], s["tool"], s["elapsed_seconds"],
                )

        # Force cleanup if too many stuck
        if len(stuck) > config.max_concurrent:
            logger.warning("health: too many stuck executions (%d), force cleaning", len(stuck))
            engine.force_cleanup()

        # Log health metrics
        uptime = now - self._start_time
        active = engine.active_count
        with self._lock:
            req_count = self._request_count
            err_count = self._error_count
        if active > 0 or req_count > 0:
            logger.info(
                "health: uptime=%.0fs active=%d requests=%d errors=%d",
                uptime, active, req_count, err_count,
            )

    def record_request(self) -> None:
        with self._lock:
            self._request_count += 1

    def record_error(self) -> None:
        with self._lock:
            self._error_count += 1

    def get_status(self) -> dict:
        uptime = time.monotonic() - self._start_time
        with self._lock:
            return {
                "status": "healthy",
                "uptime_seconds": round(uptime, 1),
                "active_executions": engine.active_count,
                "total_requests": self._request_count,
                "total_errors": self._error_count,
                "tools_registered": len(registry.tool_names()),
                "memory_mb": _get_memory_mb(),
            }


health = HealthMonitor()


def _get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    try:
        import resource as _resource
        usage = _resource.getrusage(_resource.RUSAGE_SELF)
        return round(usage.ru_maxrss / 1024, 1)  # Linux: bytes→MB
    except Exception:
        return 0.0


# ── Lifespan ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app):
    """Server lifecycle — startup and shutdown."""
    logger.info("Server starting up...")
    logger.info("Registered %d tools: %s", len(ALL_TOOLS), [t.name for t in ALL_TOOLS])

    # Verify critical binaries
    import shutil
    for bin_name in ["nmap", "curl"]:
        if shutil.which(bin_name):
            logger.info("Startup check OK: %s found", bin_name)
        else:
            logger.warning("Startup check WARN: %s not found in PATH", bin_name)

    health.start()
    logger.info("Health monitor active")

    yield

    health.stop()
    engine.force_cleanup()
    logger.info("Server shut down cleanly")


# ── FastMCP ─────────────────────────────────────────────────────
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


# Register all tools with safe_execute wrapper
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
            health.record_request()
            try:
                logger.info("request=%s tool=%s args=%s", request_id, t.name, list(kwargs.keys()))
                result = await t.safe_execute(kwargs)
                if isinstance(result, dict) and "content" in result:
                    for block in result["content"]:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return block["text"]
                return json.dumps(result, indent=2)
            except asyncio.CancelledError:
                logger.warning("request=%s tool=%s cancelled", request_id, t.name)
                return json.dumps({"error": "Request cancelled"})
            except Exception as e:
                health.record_error()
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


# ── Health Check Tool ───────────────────────────────────────────
@mcp.tool()
def health_check() -> str:
    """Check server health, memory, active executions, and registered tools."""
    status = health.get_status()
    status["available_tools"] = registry.tool_names()
    stuck = engine.get_stuck_executions()
    if stuck:
        status["stuck_executions"] = stuck
    return json.dumps(status, indent=2)


# ── Force Cleanup Tool ──────────────────────────────────────────
@mcp.tool()
def force_cleanup() -> str:
    """Force cleanup all stuck executions. Use when server appears unresponsive."""
    count = engine.force_cleanup()
    gc.collect()
    return json.dumps({
        "status": "cleaned",
        "requests_cleaned": count,
        "message": f"Force-cleaned {count} tracked executions and ran GC",
    }, indent=2)


# ── Middleware ───────────────────────────────────────────────────
class TokenAuthMiddleware:
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


# ── Main ────────────────────────────────────────────────────────
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

    # Graceful shutdown
    def _shutdown_handler(signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        health.stop()
        engine.force_cleanup()

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    uvicorn.run(app, host=config.host, port=config.port)
