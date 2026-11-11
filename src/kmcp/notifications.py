"""MCP server→client notification helpers.
All helpers are best-effort: if the Context (or its active session) is not
available the call is a safe no-op. For a local single-user server this is
enough — notifications are emitted on the request's active session.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context

logger = logging.getLogger("kmcp.notifications")


def _session(ctx: Any) -> Any:
    """Return the active MCP ServerSession from a Context, or None."""
    try:
        if ctx is None:
            return None
        session = getattr(ctx, "session", None)
        if session is None:
            request_context = getattr(ctx, "request_context", None)
            session = getattr(request_context, "session", None) if request_context else None
        if session is None:
            return None
        if not hasattr(session, "send_notification"):
            return None
        return session
    except Exception:  # noqa: BLE001
        return None


def _emit(session: Any, coro: Any) -> None:
    """Schedule a notification coroutine fire-and-forget on the loop."""
    try:
        task = asyncio.create_task(coro)
        task.add_done_callback(_swallow_task_error)
    except RuntimeError:
        # No running loop (e.g. context teardown) — run it synchronously.
        try:
            asyncio.run(coro)
        except Exception:
            logger.debug("notification failed (session closing?)", exc_info=True)


def _swallow_task_error(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.debug("notification failed (session closing?)", exc_info=exc)


def notify_resource_updated(ctx: Context | None, uri: str) -> None:
    """Notify the client that a resource changed."""
    session = _session(ctx)
    if session is None:
        return
    try:
        send = getattr(session, "send_resource_updated", None)
        if send is not None:
            from pydantic.networks import AnyUrl

            _emit(session, send(AnyUrl(uri)))
            return
        from mcp.types import (
            ResourceUpdatedNotification,
            ResourceUpdatedNotificationParams,
        )
        from pydantic.networks import AnyUrl

        notification = ResourceUpdatedNotification(
            params=ResourceUpdatedNotificationParams(uri=AnyUrl(uri))
        )
        _emit(session, session.send_notification(notification))
    except Exception:
        logger.debug("resource-updated notification failed", exc_info=True)


def notify_resources_changed(ctx: Context | None) -> None:
    """Notify the client that the resource list changed."""
    session = _session(ctx)
    if session is None:
        return
    try:
        from mcp.types import ResourceListChangedNotification, ServerNotification

        _emit(
            session,
            session.send_notification(ServerNotification(ResourceListChangedNotification())),
        )
    except Exception:
        logger.debug("resources-changed notification failed", exc_info=True)


def notify_tools_changed(ctx: Context | None) -> None:
    """Notify the client that the tool list changed."""
    session = _session(ctx)
    if session is None:
        return
    try:
        _emit(session, session.send_tool_list_changed())
    except Exception:
        logger.debug("tool-list-changed notification failed", exc_info=True)


def notify_prompts_changed(ctx: Context | None) -> None:
    """Notify the client that the prompt list changed."""
    session = _session(ctx)
    if session is None:
        return
    try:
        _emit(session, session.send_prompt_list_changed())
    except Exception:
        logger.debug("prompt-list-changed notification failed", exc_info=True)


def emit_log(ctx: Context | None, level: str, message: str) -> None:
    """Emit an MCP protocol-level log message on the session."""
    session = _session(ctx)
    if session is None:
        return
    try:
        _emit(session, session.send_log_message(level, message, logger="kmcp"))
    except Exception:
        logger.debug("log-message notification failed", exc_info=True)
