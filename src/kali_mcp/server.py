"""MCP Server — hardened SSE transport, tool registration, request handling."""

from __future__ import annotations

import asyncio
import gc
import inspect
import json
import logging
import os
import signal
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Union

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.server.fastmcp.tools.base import Tool as MCPTool
from mcp.server.fastmcp.utilities.func_metadata import func_metadata

from kali_mcp.config import config
from kali_mcp.db import manager as db_manager
from kali_mcp.execution import engine, reset_progress_cb, set_progress_cb
from kali_mcp.logging_utils import setup_logging
from kali_mcp.monitor import Monitor
from kali_mcp.monitor.sessions import session_registry
from kali_mcp.notifications import emit_log, notify_resource_updated
from kali_mcp.prompts import register_prompts
from kali_mcp.registry import registry
from kali_mcp.resources import register_resources

# Import all tools (triggers registration)
from kali_mcp.tools import ALL_TOOLS
from kali_mcp.utils.vault import ensure_vault_dirs

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
                    s["request_id"],
                    s["tool"],
                    s["elapsed_seconds"],
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
                uptime,
                active,
                req_count,
                err_count,
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

# Interactive monitor — aggregates sessions, active jobs, and health.
monitor = Monitor(session_registry, engine, health)


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
    # Initialize foundational infrastructure (Phase 1)
    try:
        ensure_vault_dirs()
        logger.info("Vault directories initialized")
    except Exception:
        logger.exception("Vault initialization failed")

    try:
        if getattr(config, "db_enabled", True):
            _db = db_manager.get_db()
            logger.info("Database initialized (path=%s)", str(config.db_path))
    except Exception:
        logger.exception("Database initialization failed")

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

# Resources + prompts (protocol-level metadata surfaced to clients)
register_resources(mcp, health=health)
register_prompts(mcp)


# Register all tools with safe_execute wrapper
for tool_instance in ALL_TOOLS:
    registry.register(tool_instance)

    def _make_handler(t):
        schema = t.input_schema()
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Map JSON schema types to Python types
        TYPE_MAP = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "object": dict,
            "array": list,
        }

        params = []
        for name, prop in properties.items():
            has_default = "default" in prop
            is_required = name in required
            json_type = prop.get("type", "string")
            if isinstance(json_type, list):
                # Union type (e.g. ["object", "string"]) → Union[dict, str]
                py_types = tuple(TYPE_MAP.get(t, str) for t in json_type)
                py_type = py_types[0] if len(py_types) == 1 else Union[py_types]
            else:
                py_type = TYPE_MAP.get(json_type, str)

            if has_default:
                default = prop.get("default")
                params.append(
                    inspect.Parameter(
                        name,
                        inspect.Parameter.KEYWORD_ONLY,
                        default=default,
                        annotation=py_type,
                    )
                )
            elif is_required:
                params.append(
                    inspect.Parameter(
                        name,
                        inspect.Parameter.KEYWORD_ONLY,
                        annotation=py_type,
                    )
                )
            else:
                # Optional — default to None, type is Optional[py_type]
                params.append(
                    inspect.Parameter(
                        name,
                        inspect.Parameter.KEYWORD_ONLY,
                        default=None,
                        annotation=py_type | None,
                    )
                )

        sig = inspect.Signature(params)

        async def handler(ctx: Context, **kwargs) -> str:
            request_id = uuid.uuid4().hex[:12]
            health.record_request()
            # Track MCP client session for interactive monitoring
            _session = getattr(ctx, "session", None)
            if _session is not None:
                _session_id = id(_session)
                session_registry.on_connect(_session_id)
                session_registry.on_activity(_session_id)

            async def progress(completed, total, message=None) -> None:
                try:
                    await ctx.report_progress(completed, total, message=message)
                except Exception:
                    pass  # client didn't ask for progress — no-op

            token = set_progress_cb(progress)
            try:
                emit_log(ctx, "info", f"Starting {t.name} ({request_id})")
                # Coerce string values to correct types based on schema
                for pname, prop in properties.items():
                    if pname in kwargs and kwargs[pname] is not None:
                        expected = prop.get("type")
                        val = kwargs[pname]
                        if expected == "integer" and isinstance(val, str):
                            kwargs[pname] = int(val)
                        elif expected == "number" and isinstance(val, str):
                            kwargs[pname] = float(val)
                        elif expected == "boolean" and isinstance(val, str):
                            kwargs[pname] = val.lower() in ("1", "true", "yes")
                        elif expected == "boolean" and isinstance(val, bool):
                            pass  # already correct
                        elif isinstance(expected, list) and isinstance(val, str):
                            # Union type allowing object/array — coerce JSON
                            # strings; non-JSON plain text stays a string
                            if any(t in ("object", "array") for t in expected):
                                try:
                                    kwargs[pname] = json.loads(val)
                                except json.JSONDecodeError:
                                    pass
                        elif (
                            expected == "object"
                            and isinstance(val, str)
                            or expected == "array"
                            and isinstance(val, str)
                        ):
                            kwargs[pname] = json.loads(val)
                logger.info(
                    "request=%s tool=%s args=%s",
                    request_id,
                    t.name,
                    list(kwargs.keys()),
                )
                result = await t.safe_execute(kwargs)
                emit_log(ctx, "info", f"Completed {t.name} ({request_id})")
                if t.name == "file_write":
                    notify_resource_updated(ctx, "kali://artifacts")
                if isinstance(result, dict) and "content" in result:
                    for block in result["content"]:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return block["text"]
                return json.dumps(result, indent=2)
            except asyncio.CancelledError:
                logger.warning("request=%s tool=%s cancelled", request_id, t.name)
                emit_log(ctx, "warning", f"Cancelled {t.name} ({request_id})")
                return json.dumps({"error": "Request cancelled"})
            except Exception:
                health.record_error()
                logger.exception("request=%s catastrophic error in tool %s", request_id, t.name)
                emit_log(ctx, "error", f"Failed {t.name} ({request_id})")
                return json.dumps({"error": "Tool execution failed"}, indent=2)
            finally:
                reset_progress_cb(token)

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
        context_kwarg="ctx",
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
    return json.dumps(
        {
            "status": "cleaned",
            "requests_cleaned": count,
            "message": f"Force-cleaned {count} tracked executions and ran GC",
        },
        indent=2,
    )


# ── File Download Endpoint ─────────────────────────────────────
async def download_file(request):
    """Serve a file download by path."""
    from starlette.responses import FileResponse, JSONResponse

    path = request.query_params.get("path", "")
    if not path:
        return JSONResponse({"error": "Missing path parameter"}, status_code=400)
    if not os.path.isfile(path):
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(path, media_type="application/octet-stream")


# ── Monitor Endpoints ──────────────────────────────────────────────
async def monitor_stream(request):
    """Server-sent events stream of live monitor snapshots.

    Connects a client to the monitor's broadcast queue. Sends an immediate
    snapshot, then pushes new snapshots whenever state changes (or every
    second as a heartbeat).
    """
    from starlette.responses import StreamingResponse

    queue = monitor.subscribe()

    async def event_generator():
        # Immediate snapshot on connect
        snapshot = monitor.build_snapshot()
        yield f"data: {json.dumps(snapshot)}\n\n"

        try:
            while True:
                try:
                    snapshot = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(snapshot)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat: send a fresh snapshot every second
                    snapshot = monitor.build_snapshot()
                    yield f"data: {json.dumps(snapshot)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            monitor.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def monitor_action(request):
    """Execute a monitor action: kill_job, force_cleanup, or get_snapshot."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    req = Request(request.scope, request.receive)
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    action = body.get("action")
    if action == "kill_job":
        result = await monitor.kill_job(body.get("request_id", ""))
    elif action == "force_cleanup":
        result = await monitor.force_cleanup()
    elif action == "get_snapshot":
        result = monitor.build_snapshot()
    else:
        return JSONResponse({"error": "unknown action"}, status_code=400)

    return JSONResponse(result)


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
def main() -> None:
    """Run the MCP server over HTTP (SSE or streamable-http)."""
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
        logger.warning(
            "No MCP_API_TOKEN set — server is open. Set MCP_API_TOKEN in .env for production."
        )

    # Graceful shutdown
    def _shutdown_handler(signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        health.stop()
        engine.force_cleanup()

    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    # File download route
    from starlette.routing import Route

    app.routes.insert(0, Route("/download", download_file, methods=["GET"]))
    app.routes.insert(0, Route("/monitor/stream", monitor_stream, methods=["GET"]))
    app.routes.insert(0, Route("/monitor/action", monitor_action, methods=["POST"]))

    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
