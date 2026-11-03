"""Unit tests for notifications.py (MCP server→client notification helpers)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kali_mcp.notifications import (
    emit_log,
    notify_prompts_changed,
    notify_resource_updated,
    notify_resources_changed,
    notify_tools_changed,
)


class FakeSession:
    """Minimal stand-in for an MCP ServerSession."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, object]] = []

    def send_notification(self, notification):
        self.sent.append(("notification", notification))
        return MagicMock()

    def send_resource_updated(self, uri):
        self.sent.append(("resource_updated", uri))
        return MagicMock()

    def send_tool_list_changed(self):
        self.sent.append(("tool_list_changed", None))
        return MagicMock()

    def send_prompt_list_changed(self):
        self.sent.append(("prompt_list_changed", None))
        return MagicMock()

    def send_log_message(self, level, message, logger):
        self.sent.append(("log", (level, message, logger)))
        return MagicMock()


class FakeCtx:
    def __init__(self, session):
        self.session = session
        self.request_context = MagicMock()
        self.request_context.session = session


class TestNotificationHelpers:
    def test_notify_resource_updated(self) -> None:
        session = FakeSession()
        ctx = FakeCtx(session)
        notify_resource_updated(ctx, "kali://artifacts/x")
        assert any(kind == "resource_updated" for kind, _ in session.sent)

    def test_notify_resource_updated_no_session(self) -> None:
        # Must not raise when ctx is None or has no usable session
        notify_resource_updated(None, "kali://artifacts/x")
        notify_resource_updated(object(), "kali://artifacts/x")

    def test_notify_resources_changed(self) -> None:
        session = FakeSession()
        ctx = FakeCtx(session)
        notify_resources_changed(ctx)
        # notify_resources_changed uses send_notification internally
        assert any(kind == "notification" for kind, _ in session.sent)

    def test_notify_resources_changed_no_session(self) -> None:
        notify_resources_changed(None)

    def test_notify_tools_changed(self) -> None:
        session = FakeSession()
        ctx = FakeCtx(session)
        notify_tools_changed(ctx)
        assert any(kind == "tool_list_changed" for kind, _ in session.sent)

    def test_notify_prompts_changed(self) -> None:
        session = FakeSession()
        ctx = FakeCtx(session)
        notify_prompts_changed(ctx)
        assert any(kind == "prompt_list_changed" for kind, _ in session.sent)

    def test_emit_log(self) -> None:
        session = FakeSession()
        ctx = FakeCtx(session)
        emit_log(ctx, "warning", "something happened")
        assert any(kind == "log" for kind, _ in session.sent)

    def test_emit_log_no_session(self) -> None:
        emit_log(None, "info", "hi")

    def test_session_without_send_notification_is_ignored(self) -> None:
        session = MagicMock()
        del session.send_notification
        del session.send_resource_updated
        del session.send_tool_list_changed
        del session.send_prompt_list_changed
        del session.send_log_message
        ctx = FakeCtx(session)
        # All must be no-ops, not raise
        notify_resource_updated(ctx, "kali://x")
        notify_resources_changed(ctx)
        notify_tools_changed(ctx)
        notify_prompts_changed(ctx)
        emit_log(ctx, "info", "hi")
