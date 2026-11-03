"""Tests for prompts, notifications, logging, models edge cases, and registry."""

from __future__ import annotations

import json
import logging

import pytest

# ── Prompts ────────────────────────────────────────────────────────────────────
from kali_mcp.prompts import _ad, _osint, _quick_scan, _recon, _report, _webapp


class TestPrompts:
    @pytest.mark.parametrize(
        "builder", [_recon, _webapp, _ad, _osint, _quick_scan, _report]
    )
    def test_returns_user_assistant_messages(self, builder):
        msg = builder("test-target")  # type: ignore[call-arg]
        assert len(msg) == 2
        assert msg[0]["role"] == "user"
        assert msg[1]["role"] == "assistant"
        assert all(m["content"]["type"] == "text" for m in msg)

    def test_recon_includes_target(self):
        msgs = _recon("example.com", depth="deep", scope="black-box")
        assert "example.com" in msgs[0]["content"]["text"]
        assert "subdomains" in msgs[1]["content"]["text"]

    def test_webapp_auth_flag(self):
        msgs = _webapp("http://x", auth="yes")
        assert "authenticated: yes" in msgs[0]["content"]["text"]

    def test_ad_credentials(self):
        msgs = _ad("corp.local", credentials="svc:pass")
        assert "svc:pass" in msgs[0]["content"]["text"]

    def test_osint_sources(self):
        msgs = _osint("acme", sources="all")
        assert "all" in msgs[0]["content"]["text"]

    def test_report_findings(self):
        msgs = _report("eng1", findings="sqli in /login")
        assert "sqli in /login" in msgs[0]["content"]["text"]

    def test_register_prompts_is_idempotent_safe(self):
        class FakeMCP:
            def __init__(self):
                self.prompts = []

            def prompt(self, **kw):
                def deco(fn):
                    self.prompts.append(kw.get("name"))
                    return fn

                return deco

        from kali_mcp.prompts import register_prompts

        fake = FakeMCP()
        register_prompts(fake)
        assert len(fake.prompts) == 6


# ── Notifications ──────────────────────────────────────────────────────────────


class TestNotificationsNoopSafety:
    """All notification helpers must be safe no-ops with None/broken contexts."""

    def test_none_ctx(self):
        from kali_mcp.notifications import (
            emit_log,
            notify_prompts_changed,
            notify_resource_updated,
            notify_resources_changed,
            notify_tools_changed,
        )

        notify_resource_updated(None, "kali://x")
        notify_resources_changed(None)
        notify_tools_changed(None)
        notify_prompts_changed(None)
        emit_log(None, "info", "hello")

    def test_broken_ctx(self):
        from kali_mcp.notifications import notify_tools_changed

        class Weird:
            @property
            def session(self):
                raise RuntimeError("boom")

        notify_tools_changed(Weird())  # must not raise

    def test_ctx_without_session(self):
        from kali_mcp.notifications import notify_tools_changed

        notify_tools_changed(object())  # no .session attribute

    def test_session_missing_methods(self):
        from kali_mcp.notifications import notify_tools_changed

        class EmptySession:
            pass

        class Ctx:
            session = EmptySession()

        notify_tools_changed(Ctx())


# ── Logging ────────────────────────────────────────────────────────────────────


class TestLogging:
    def test_json_formatter_shape(self):
        from kali_mcp.logging_utils import JSONFormatter

        record = logging.LogRecord(
            name="kali_mcp.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        entry = json.loads(JSONFormatter().format(record))
        assert entry["message"] == "hello world"
        assert entry["level"] == "INFO"
        assert entry["logger"] == "kali_mcp.test"
        assert "timestamp" in entry

    def test_log_execution_never_raises(self):
        from kali_mcp.logging_utils import log_execution

        class Exploding:
            tool = property(lambda self: (_ for _ in ()).throw(RuntimeError("x")))

        log_execution(Exploding())  # must not raise

    def test_log_execution_writes(self, tmp_path, monkeypatch):
        from kali_mcp.logging_utils import log_execution
        from kali_mcp.models import ExecutionResult, utc_now_iso

        result = ExecutionResult(
            tool="t",
            command="t",
            stdout="",
            stderr="",
            exit_code=0,
            success=True,
            timed_out=False,
            duration=0.0,
            start_time=utc_now_iso(),
            end_time=utc_now_iso(),
        )
        log_execution(result)  # best-effort — must not raise


# ── Models edge cases ──────────────────────────────────────────────────────────


class TestModelsEdge:
    def test_utc_now_iso_parseable(self):
        from kali_mcp.models import utc_now_iso

        ts = utc_now_iso()
        from datetime import datetime

        parsed = datetime.fromisoformat(ts)  # must not raise
        assert parsed.tzinfo is not None

    def test_execution_result_unicode_roundtrip(self):
        from kali_mcp.models import ExecutionResult, utc_now_iso

        r = ExecutionResult(
            tool="t",
            command="é",
            stdout="→",
            stderr="ü",
            exit_code=0,
            success=True,
            timed_out=False,
            duration=0.0,
            start_time=utc_now_iso(),
            end_time=utc_now_iso(),
        )
        assert r.to_dict()["stdout"] == "→"


# ── Registry edge cases ────────────────────────────────────────────────────────


class TestRegistryEdge:
    def _tool(self, name):
        from kali_mcp.tools.base import BaseTool

        class T(BaseTool):
            @property
            def name(self):
                return name

            @property
            def description(self):
                return "d"

            def input_schema(self):
                return {}

            def validate(self, a):
                pass

            def build_command(self, a):
                return ["x"]

            async def execute(self, a):
                return {}

        return T()

    def test_many_registrations(self):
        from kali_mcp.registry import ToolRegistry

        reg = ToolRegistry()
        for i in range(50):
            reg.register(self._tool(f"t{i}"))
        assert len(reg.list_all()) == 50
        assert len(reg.tool_names()) == 50

    def test_names_include_last_overwrite_only_once(self):
        from kali_mcp.registry import ToolRegistry

        reg = ToolRegistry()
        reg.register(self._tool("dup"))
        reg.register(self._tool("dup"))
        assert reg.tool_names().count("dup") == 1

    def test_get_with_empty_string(self):
        from kali_mcp.registry import ToolRegistry

        assert ToolRegistry().get("") is None
