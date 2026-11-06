"""Tests for workflow iteration caps and the engine-level scope gate (Phase 1).

Covers:
- foreach iteration cap (``MAX_ITERATIONS``) enforced by the DAG engine
- per-step scope gate: every step type is checked before execution
- per-item scope gate on foreach over dynamically discovered targets
"""

from __future__ import annotations

import pytest

from kali_mcp.scope import Scope
from kali_mcp.workflow import dag_executor as de
from kali_mcp.workflow.dag_executor import MAX_ITERATIONS, PlaybookEngine, run_playbook_async
from kali_mcp.workflow.scope_gate import (
    ScopeViolationError,
    assert_target_allowed,
    extract_targets,
    gate_step_args,
)
from kali_mcp.workflow.yaml_loader import PlaybookDefinition, StepDefinition


def _defn(steps, inputs=None):
    return PlaybookDefinition(
        name="limits.test",
        version="1.0.0",
        inputs=inputs or {},
        execution={"max_parallel": 2},
        steps=steps,
        raw={},
    )


class TestExtractTargets:
    def test_target_keys_are_matched(self):
        args = {"target": " example.com ", "ports": [80, 443], "extra": "other.com"}
        assert extract_targets(args) == ["example.com"]

    def test_list_values_flattened(self):
        args = {"targets": ["127.0.0.1", "blocked.example.com", "{{steps.x.items}}"]}
        assert extract_targets(args) == ["127.0.0.1", "blocked.example.com"]

    def test_unresolved_templates_skipped(self):
        args = {"host": "{{steps.dns.resolved_hosts}}"}
        assert extract_targets(args) == []

    def test_scalar_lists_keep_ints(self):
        args = {"ips": [10, 20]}
        assert extract_targets(args) == ["10", "20"]

    def test_deduplicated(self):
        args = {"target": "a.com", "host": "a.com"}
        assert extract_targets(args) == ["a.com"]


class TestScopeGate:
    def test_permissive_scope_passes(self):
        # No env vars configured: permissive mode → no throw
        gate_step_args({"target": "anything.com"}, step_id="s1")

    def test_excluded_target_raises(self, monkeypatch):
        scope = Scope(allowed_targets=(), excluded_targets=("*.external.com",))
        with pytest.raises(ScopeViolationError, match="excluded"):
            gate_step_args({"target": "node.external.com"}, step_id="s2", scope=scope)

    def test_outside_allowed_target_raises(self, monkeypatch):
        scope = Scope(allowed_targets=("*.example.com",))
        with pytest.raises(ScopeViolationError, match="not allowed|not in allowed"):
            gate_step_args({"target": "evil.com"}, step_id="s3", scope=scope)

    def test_allowed_target_in_scope_passes(self):
        scope = Scope(allowed_targets=("*.example.com",))
        gate_step_args({"target": "www.example.com"}, step_id="s4", scope=scope)

    def test_expired_scope_raises(self):
        scope = Scope(expiration="2020-01-01T00:00:00+00:00")
        with pytest.raises(ScopeViolationError, match="expired"):
            gate_step_args({"target": "a.com"}, step_id="s5", scope=scope)

    def test_assert_target_allowed_delegates(self):
        scope = Scope(allowed_targets=(), excluded_targets=("bad.x",))
        with pytest.raises(ScopeViolationError):
            assert_target_allowed("bad.x", scope=scope)

    def test_per_item_list_check(self):
        scope = Scope(allowed_targets=("*.example.com",))
        with pytest.raises(ScopeViolationError, match="external.host"):
            gate_step_args(
                {"targets": ["www.example.com", "external.host"]},
                step_id="s6",
                scope=scope,
            )


async def _run(defn, monkeypatch=None):
    engine = PlaybookEngine()
    if monkeypatch is not None:
        monkeypatch.setattr(engine, "_run_tool_step", _fake_tool)
    return await engine.run(defn)


async def _fake_tool(step, state):
    return {"step": step.id, "tool": step.tool, "ran": True}


class TestEngineIntegration:
    async def test_scope_violation_marks_step_failed(self, monkeypatch):
        scope = Scope(allowed_targets=("*.example.com",))
        monkeypatch.setattr(de, "load_scope", lambda: scope, raising=False)
        monkeypatch.setattr(
            "kali_mcp.workflow.scope_gate.load_scope", lambda: scope
        )
        steps = [
            StepDefinition(id="probe", tool="dnsx", args={"target": "evil.com"}),
            StepDefinition(id="after", tool="httpx",
                           args={"url": "http://example.com"},
                           depends_on=["probe"]),
        ]
        result = await _run(_defn(steps))
        payload = __import__("json").loads(result.stdout)
        step_results = payload["step_results"]
        assert step_results["probe"]["scope_violation"] is True
        assert "evil.com" in step_results["probe"]["error"]

    async def test_scope_pass_through_when_permissive(self, monkeypatch):
        monkeypatch.setattr(
            "kali_mcp.workflow.scope_gate.load_scope",
            lambda: Scope(),
        )
        steps = [StepDefinition(id="probe", tool="dnsx", args={"target": "anything.com"})]
        result = await _run(_defn(steps), monkeypatch)
        payload = __import__("json").loads(result.stdout)
        res = payload["step_results"]["probe"]
        assert res.get("ran") is True

    async def test_foreach_cap_exceeded(self, monkeypatch):
        # foreach over more than MAX_ITERATIONS items → step fails, tool never runs
        big = [f"host{i}.com" for i in range(MAX_ITERATIONS + 10)]
        step = StepDefinition(
            id="iter", tool="dnsx", foreach="dns.resolved_hosts"
        )
        engine = PlaybookEngine()
        engine._step_results["dns"] = {"resolved_hosts": big}
        res = await engine._run_foreach(step, [step], {})
        assert res["error"].startswith("iteration_cap_exceeded")
        assert res["count"] == 0

    async def test_foreach_within_cap_runs(self, monkeypatch):
        small = ["a.com", "b.com"]
        step = StepDefinition(id="iter", tool="dnsx", foreach="dns.resolved_hosts")
        engine = PlaybookEngine()
        engine._step_results["dns"] = {"resolved_hosts": small}
        # gate must be permissive
        monkeypatch.setattr(
            "kali_mcp.workflow.scope_gate.load_scope", lambda: Scope()
        )
        monkeypatch.setattr(
            "kali_mcp.workflow.dag_executor.gate_step_args",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            engine, "_execute_single_step",
            lambda iter_step, state: _fake_tool(iter_step, state),
        )
        res = await engine._run_foreach(step, [step], {})
        assert res["count"] == 2
        assert res["foreach_results"][0]["ran"] is True

    async def test_foreach_item_out_of_scope_flags_item(self, monkeypatch):
        scope = Scope(allowed_targets=("*.example.com",))
        monkeypatch.setattr(
            "kali_mcp.workflow.scope_gate.load_scope", lambda: scope
        )
        step = StepDefinition(
            id="iter",
            tool="dnsx",
            foreach="dns.resolved_hosts",
            args={"host": "{{target}}"},
        )
        engine = PlaybookEngine()
        engine._step_results["dns"] = {"resolved_hosts": ["evil.com", "ok.com"]}
        monkeypatch.setattr(
            engine, "_run_tool_step", lambda iter_step, state: _fake_tool(iter_step, state)
        )
        res = await engine._run_foreach(step, [step], {})
        items = res["foreach_results"]
        assert res["count"] == 2
        # evil.com must be caught per-item
        flagged = [i for i in items if i.get("scope_violation")]
        assert any("evil.com" in str(i.get("error", "")) for i in flagged), res
        # ok.com must have run (permissive only for allowed target)
        ran = [i for i in items if not i.get("scope_violation")]
        assert not ran or all(i.get("ran") for i in ran)

    def test_custom_step_unregistered_module(self, monkeypatch):
        step = StepDefinition(id="mod", tool="ghost.module", type="custom")
        engine = PlaybookEngine()
        result = __import__(
            "asyncio"
        ).run(engine._run_custom_step(step, {"playbook_name": "x"}))
        assert "module not registered: ghost.module" in result["error"]


class TestLegacyCustomStep:
    """Bare ``type: custom`` steps keep the legacy pass-through behavior."""

    async def test_step_without_module_ref_passthrough(self):
        step = StepDefinition(id="plain", tool=None, type="custom")
        result = await PlaybookEngine()._run_custom_step(step, {"playbook_name": "x"})
        assert result["status"] == "executed"
        assert result["type"] == "custom"


class TestAsyncEntry:
    """run_playbook_async must work when awaited from a running event loop.

    This is the regression test for the ``asyncio.run() cannot be called
    from a running event loop`` crash that occurred when MCP tool handlers
    awaited the old sync ``run_playbook`` wrapper.
    """

    async def test_run_playbook_async_inside_running_loop(self):
        # Awaiting run_playbook_async from within this async test (which runs
        # inside an active asyncio loop courtesy of pytest-asyncio) must not
        # raise and must return a completed ExecutionResult.
        pb = PlaybookDefinition(
            name="async-regression",
            version="1.0.0",
            inputs={},
            execution={"max_parallel": 2},
            steps=[
                StepDefinition(id="validate", type="scope_check", args={"target": "example.com"})
            ],
            raw={},
        )
        res = await run_playbook_async(pb, resume=False)
        assert res.success is True
        assert res.exit_code == 0
        payload = __import__("json").loads(res.stdout)
        assert payload["status"] == "completed"
        assert de.RUN_STATUS.get("async-regression", {}).get("status") == "completed"
