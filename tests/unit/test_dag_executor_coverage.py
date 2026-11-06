"""Coverage tests for dag_executor.py (DAG-based playbook execution engine).

Covers PlaybookEngine.run / _run_step / _execute_single_step / the per-type
step runners, waves / semaphore / budget, checkpoint / persist_state, resume,
on_failure, when conditions, foreach loops, run_playbook / run_playbook_async,
and the error paths (unknown step type, module not found, scope violation).

Real subprocesses, network and SQLite are mocked out via unittest.mock.patch
and AsyncMock.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kali_mcp.workflow import dag_executor as de
from kali_mcp.workflow.dag_executor import (
    MAX_ITERATIONS,
    PlaybookEngine,
    run_playbook,
    run_playbook_async,
)
from kali_mcp.workflow.modules_runtime import ModuleError
from kali_mcp.workflow.scope_gate import ScopeViolationError
from kali_mcp.workflow.yaml_loader import PlaybookDefinition, StepDefinition


# ── helpers ──────────────────────────────────────────────────────────────


def _pb(name="pb", steps=None, inputs=None, execution=None):
    return PlaybookDefinition(
        name=name,
        version="1.0",
        inputs=inputs or {},
        execution=execution or {"max_parallel": 4, "timeout": 900},
        steps=steps or [],
        raw={},
    )


def _step(
    id="s",
    tool=None,
    module=None,
    type="tool",
    depends_on=None,
    when=None,
    foreach=None,
    output_mapping=None,
    retry=0,
    on_failure="abort",
    checkpoint=False,
    budget=None,
    args=None,
    parallel=False,
):
    return StepDefinition(
        id=id,
        tool=tool,
        module=module,
        type=type,
        depends_on=list(depends_on or []),
        when=when,
        parallel=parallel,
        foreach=foreach,
        output_mapping=dict(output_mapping or {}),
        retry=retry,
        on_failure=on_failure,
        checkpoint=checkpoint,
        budget=dict(budget or {}),
        args=dict(args or {}),
    )


def _tool(result=None, *, slow=False, raise_exc=None, call_log=None):
    """Fake native tool whose safe_execute returns ``result`` (or raises).

    ``call_log`` appends the args received, useful for asserting invocation
    and ordering.
    """

    async def _safe_execute(args):
        if call_log is not None:
            call_log.append(args)
        if slow:
            await asyncio.sleep(0.2)
        if raise_exc is not None:
            raise raise_exc
        return result if result is not None else {"ok": True}

    tool = AsyncMock()
    tool.safe_execute = _safe_execute
    return tool


def _fake_registry(tools):
    reg = SimpleNamespace()
    reg.get = lambda name: tools.get(name)
    return reg


def _clear_run_status():
    de.RUN_STATUS.clear()


@contextmanager
def _env(tools=None, gate=None, db=None, no_sleep=True):
    """Common execution environment for run()-based tests.

    - fake tool registry (``tools``)
    - fake scope gate (``gate``, defaults to a permissive no-op MagicMock)
    - fake db manager (``db``, defaults to None -> SQLite skipped)
    - asyncio.sleep replaced with a no-op (keeps retry tests fast)
    """
    tools = tools or {}
    started = []

    def _start(p):
        started.append(p)
        p.start()

    _start(
        patch(
            "kali_mcp.workflow.dag_executor._get_registry",
            return_value=_fake_registry(tools),
        )
    )
    if gate is None:
        gate = MagicMock()
    _start(patch("kali_mcp.workflow.dag_executor.gate_step_args", new=gate))
    if db is not None:
        _start(patch("kali_mcp.db.manager.get_db", return_value=db))
    if no_sleep:
        _start(patch("kali_mcp.workflow.dag_executor.asyncio.sleep", new=AsyncMock()))
    try:
        yield gate
    finally:
        for p in reversed(started):
            p.stop()


# ── run() lifecycle ─────────────────────────────────────────────────────


class TestRunLifecycle:
    async def test_single_scope_check_step_completes(self):
        _clear_run_status()
        with _env():
            engine = PlaybookEngine()
            res = await engine.run(_pb(steps=[_step(id="validate", type="scope_check", args={"target": "example.com"})]))
        assert res.success is True
        assert res.exit_code == 0
        payload = json.loads(res.stdout)
        assert payload["status"] == "completed"
        assert payload["completed_steps"] == [0]

    async def test_tool_step_calls_registry_tool(self):
        _clear_run_status()
        call_log = []
        tools = {"nmap": _tool({"ports": [22]}, call_log=call_log)}
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(steps=[_step(id="scan", tool="nmap", args={"target": "example.com"})])
            )
        assert res.success is True
        assert call_log == [{"target": "example.com"}]
        payload = json.loads(res.stdout)
        assert payload["step_results"]["scan"]["ports"] == [22]

    async def test_tool_step_unknown_tool_records_error(self):
        _clear_run_status()
        tools = {}  # nothing registered
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(steps=[_step(id="scan", tool="ghost", args={"target": "example.com"})])
            )
        assert res.success is True  # a failed step still yields partial/completed
        payload = json.loads(res.stdout)
        assert payload["step_results"]["scan"]["error"] == "unknown tool"
        assert payload["step_results"]["scan"]["tool"] == "ghost"

    async def test_tool_step_missing_tool_caught(self):
        _clear_run_status()
        with _env():
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(steps=[_step(id="scan", tool=None, args={})])
            )
        payload = json.loads(res.stdout)
        assert "missing 'tool'" in payload["step_results"]["scan"]["error"]

    async def test_target_substitution(self):
        _clear_run_status()
        call_log = []
        tools = {"nmap": _tool({"ports": []}, call_log=call_log)}
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    inputs={"targets": "example.com"},
                    steps=[_step(id="scan", tool="nmap", args={"target": "{{target}}", "ports": "22"})],
                )
            )
        assert res.success is True
        assert call_log == [{"target": "example.com", "ports": "22"}]

    async def test_three_independent_steps_all_run(self):
        _clear_run_status()
        call_log = []
        tools = {f"t{i}": _tool({"i": i}, call_log=call_log) for i in range(3)}
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="a", tool="t0", args={"v": 0}),
                        _step(id="b", tool="t1", args={"v": 1}),
                        _step(id="c", tool="t2", args={"v": 2}),
                    ]
                )
            )
        assert res.success is True
        assert len(call_log) == 3
        payload = json.loads(res.stdout)
        assert len(payload["completed_steps"]) == 3

    async def test_dependency_wave_ordering(self):
        _clear_run_status()
        order = []

        async def _recording_safe_execute(args):
            order.append(args["step"])
            return {"step": args["step"]}

        tools = {}
        for name in ("first", "second"):
            t = AsyncMock()
            t.safe_execute = _recording_safe_execute
            tools[name] = t

        def _get_reg():
            reg = SimpleNamespace()
            reg.get = lambda name: tools[name]
            return reg

        _clear_run_status()
        with patch("kali_mcp.workflow.dag_executor._get_registry", return_value=_get_reg()), patch(
            "kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock()
        ), patch("kali_mcp.db.manager.get_db", return_value=None), patch(
            "kali_mcp.workflow.dag_executor.asyncio.sleep", new=AsyncMock()
        ):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="second", tool="second", args={"step": "second"}, depends_on=["first"]),
                        _step(id="first", tool="first", args={"step": "first"}),
                    ]
                )
            )
        assert res.success is True
        assert order.index("first") < order.index("second")

    async def test_overall_timeout_deadline_fails(self):
        _clear_run_status()
        # timeout=0 -> the overall deadline is already exceeded before wave 0
        with _env():
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[_step(id="s", tool="nmap", args={})],
                    execution={"max_parallel": 4, "timeout": 0},
                )
            )
        payload = json.loads(res.stdout)
        assert payload["status"] == "failed"

    async def test_step_timeout(self):
        _clear_run_status()
        tools = {"slow": _tool(slow=True)}
        # budget of 0.01s, tool sleeps 0.2s -> timeout
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[_step(id="slow", tool="slow", args={}, budget={"timeout": 0.01})],
                    execution={"max_parallel": 4, "timeout": 900},
                )
            )
        payload = json.loads(res.stdout)
        assert payload["step_results"]["slow"]["timed_out"] is True
        assert payload["step_results"]["slow"]["error"] == "timeout"

    async def test_step_exception_is_caught_and_playbook_continues(self):
        _clear_run_status()
        tools = {
            "boom": _tool(raise_exc=RuntimeError("kaboom")),
            "nmap": _tool({"ok": True}),
        }
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="boom", tool="boom", args={}, on_failure="continue"),
                        _step(id="after", tool="nmap", args={}),
                    ]
                )
            )
        payload = json.loads(res.stdout)
        assert payload["step_results"]["boom"]["error"] == "kaboom"
        assert payload["step_results"]["after"]["ok"] is True

    async def test_unknown_step_type_raises_via_execute_single_step(self):
        _clear_run_status()
        engine = PlaybookEngine()
        # Build a step bypassing StepDefinition type validation
        step = StepDefinition.__new__(StepDefinition)
        step.id = "bogus"
        step.tool = None
        step.module = None
        step.type = "not-a-real-type"
        step.depends_on = []
        step.when = None
        step.parallel = False
        step.foreach = None
        step.output_mapping = {}
        step.retry = 0
        step.on_failure = "abort"
        step.checkpoint = False
        step.budget = {}
        step.args = {}
        with patch(
            "kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock()
        ), patch("kali_mcp.db.manager.get_db", return_value=None), patch(
            "kali_mcp.workflow.dag_executor.asyncio.sleep", new=AsyncMock()
        ), patch(
            "kali_mcp.workflow.dag_executor._get_registry", return_value=_fake_registry({})
        ):
            with pytest.raises(de.PlaybookError, match="Unknown step type"):
                await engine._execute_single_step(step, {})

    async def test_checkpoint_persists_state_to_db(self):
        _clear_run_status()
        db = MagicMock()
        tools = {"nmap": _tool({"ok": True})}
        with _env(tools=tools, db=db):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="s", tool="nmap", args={}, checkpoint=True)
                    ]
                )
            )
        assert res.success is True
        db.save_workflow_run.assert_called()

    async def test_on_failure_abort_stops_dependents(self):
        _clear_run_status()
        tools = {
            "failing": _tool({"error": "x"}),
            "nmap": _tool({"ok": True}),
        }
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="failing", tool="failing", args={}, on_failure="abort"),
                        _step(id="after", tool="nmap", args={}, depends_on=["failing"]),
                    ]
                )
            )
        payload = json.loads(res.stdout)
        assert payload["step_results"]["failing"]["error"] == "x"
        assert "after" not in payload["step_results"]

    async def test_on_failure_skip_dependents_stops_dependents(self):
        _clear_run_status()
        tools = {
            "failing": _tool({"error": "x"}),
            "nmap": _tool({"ok": True}),
        }
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="failing", tool="failing", args={}, on_failure="skip_dependents"),
                        _step(id="after", tool="nmap", args={}, depends_on=["failing"]),
                    ]
                )
            )
        payload = json.loads(res.stdout)
        assert payload["step_results"]["failing"]["error"] == "x"
        assert "after" not in payload["step_results"]

    async def test_when_condition_false_skips_step(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["prior"] = {"count": 0}
        tools = {"nmap": _tool({"ok": True})}
        with _env(tools=tools):
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="skipme", tool="nmap", args={}, when="prior.count > 0"),
                    ]
                )
            )
        payload = json.loads(res.stdout)
        assert payload["step_results"]["skipme"]["skipped"] is True
        assert payload["step_results"]["skipme"]["reason"] == "when condition false"

    async def test_when_condition_true_runs_step(self):
        _clear_run_status()
        call_log = []
        tools = {"nmap": _tool({"ok": True}, call_log=call_log)}
        with _env(tools=tools):
            engine = PlaybookEngine()
            engine._step_results["prior"] = {"count": 5}
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="runme", tool="nmap", args={}, when="prior.count > 0"),
                    ]
                )
            )
        assert res.success is True
        assert call_log == [{}]

    async def test_foreach_within_cap_runs_per_item(self):
        _clear_run_status()
        call_log = []
        tools = {"dnsx": _tool(None, call_log=call_log)}
        with _env(tools=tools):
            engine = PlaybookEngine()
            engine._step_results["discover"] = {"resolved_hosts": ["a.com", "b.com"]}
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="iter", tool="dnsx", args={}, foreach="discover.resolved_hosts"),
                    ]
                )
            )
        assert res.success is True
        payload = json.loads(res.stdout)
        fr = payload["step_results"]["iter"]["foreach_results"]
        assert payload["step_results"]["iter"]["count"] == 2
        assert len(fr) == 2

    async def test_foreach_cap_exceeded(self):
        _clear_run_status()
        big = [f"h{i}.com" for i in range(MAX_ITERATIONS + 10)]
        engine = PlaybookEngine()
        engine._step_results["dns"] = {"resolved_hosts": big}
        with _env():
            res = await engine._run_foreach(
                _step(id="iter", tool="dnsx", foreach="dns.resolved_hosts"),
                [_step(id="iter", tool="dnsx", foreach="dns.resolved_hosts")],
                {},
            )
        assert res["error"].startswith("iteration_cap_exceeded")
        assert res["count"] == 0

    async def test_resume_skips_completed_steps(self):
        _clear_run_status()
        call_log = []
        tools = {"nmap": _tool({"ok": True}, call_log=call_log)}
        # prior run marked step 0 as completed
        de.RUN_STATUS["pb"] = {
            "status": "completed",
            "completed_steps": [0],
            "steps_total": 2,
        }
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="first", tool="nmap", args={}),
                        _step(id="second", tool="nmap", args={}),
                    ]
                ),
                resume=True,
            )
        payload = json.loads(res.stdout)
        # only the second step ran
        assert len(call_log) == 1
        assert payload["completed_steps"] == [0, 1]

    async def test_resume_from_persisted_db(self):
        _clear_run_status()
        call_log = []
        tools = {"nmap": _tool({"ok": True}, call_log=call_log)}
        db = MagicMock()
        db.load_workflow_run.return_value = {
            "status": "completed",
            "completed_steps": [0],
            "state": {"status": "completed", "completed_steps": [0], "steps_total": 2},
        }
        with _env(tools=tools, db=db):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[
                        _step(id="first", tool="nmap", args={}),
                        _step(id="second", tool="nmap", args={}),
                    ]
                ),
                resume=True,
            )
        payload = json.loads(res.stdout)
        assert len(call_log) == 1
        assert db.load_workflow_run.call_count >= 1

    async def test_resume_with_no_prior_runs_all(self):
        _clear_run_status()
        call_log = []
        tools = {"nmap": _tool({"ok": True}, call_log=call_log)}
        with _env(tools=tools):
            engine = PlaybookEngine()
            res = await engine.run(
                _pb(
                    steps=[_step(id="only", tool="nmap", args={})]
                ),
                resume=True,
            )
        assert res.success is True
        assert len(call_log) == 1

    async def test_run_playbook_async_entry_point(self):
        _clear_run_status()
        with _env():
            res = await run_playbook_async(
                _pb(steps=[_step(id="s", type="scope_check", args={"target": "example.com"})])
            )
        assert res.success is True
        assert res.exit_code == 0

    async def test_run_playbook_entry_point(self):
        _clear_run_status()
        with _env():
            res = await run_playbook(
                _pb(steps=[_step(id="s", type="scope_check", args={"target": "example.com"})])
            )
        assert res.success is True
        assert res.exit_code == 0


# ── _run_step / _execute_single_step direct ─────────────────────────────


class TestRunStepAndExecuteSingleStep:
    async def test_run_step_when_false(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["prior"] = {"count": 0}
        with _env():
            res = await engine._run_step(
                _step(id="s", tool="nmap", args={}, when="prior.count > 0"), [], {}
            )
        assert res == {"step": "s", "skipped": True, "reason": "when condition false"}

    async def test_run_step_foreach(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["dns"] = {"resolved_hosts": ["x.com"]}
        with _env():
            res = await engine._run_step(
                _step(id="s", tool="dnsx", foreach="dns.resolved_hosts", args={}),
                [_step(id="s", tool="dnsx", foreach="dns.resolved_hosts", args={})],
                {},
            )
        assert res["count"] == 1
        assert res["step"] == "s"

    async def test_run_step_retry_then_success(self):
        _clear_run_status()
        calls = {"n": 0}

        async def _flaky(args):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("transient")
            return {"ok": True}

        tool = AsyncMock()
        tool.safe_execute = _flaky
        _clear_run_status()
        engine = PlaybookEngine()
        with patch(
            "kali_mcp.workflow.dag_executor._get_registry",
            return_value=_fake_registry({"flaky": tool}),
        ), patch("kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock()), patch(
            "kali_mcp.db.manager.get_db", return_value=None
        ), patch(
            "kali_mcp.workflow.dag_executor.asyncio.sleep", new=AsyncMock()
        ):
            res = await engine._run_step(
                _step(id="s", tool="flaky", args={}, retry=1), [], {}
            )
        assert res == {"ok": True}
        assert calls["n"] == 2

    async def test_run_step_retry_exhausted_raises(self):
        _clear_run_status()
        tool = AsyncMock()
        tool.safe_execute = AsyncMock(side_effect=RuntimeError("always"))
        engine = PlaybookEngine()
        with patch(
            "kali_mcp.workflow.dag_executor._get_registry",
            return_value=_fake_registry({"flaky": tool}),
        ), patch("kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock()), patch(
            "kali_mcp.db.manager.get_db", return_value=None
        ), patch(
            "kali_mcp.workflow.dag_executor.asyncio.sleep", new=AsyncMock()
        ):
            with pytest.raises(RuntimeError, match="always"):
                await engine._run_step(
                    _step(id="s", tool="flaky", args={}, retry=1), [], {}
                )

    async def test_run_step_scope_violation_not_retried(self):
        _clear_run_status()
        engine = PlaybookEngine()
        with patch(
            "kali_mcp.workflow.dag_executor.gate_step_args",
            new=MagicMock(side_effect=ScopeViolationError("out of scope")),
        ), patch("kali_mcp.db.manager.get_db", return_value=None), patch(
            "kali_mcp.workflow.dag_executor.asyncio.sleep", new=AsyncMock()
        ):
            res = await engine._run_step(_step(id="s", tool="nmap", args={}), [], {})
        assert res["scope_violation"] is True
        assert "out of scope" in res["error"]

    async def test_execute_single_step_module_not_found(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._subst_target = "example.com"
        with patch(
            "kali_mcp.workflow.dag_executor.load_module", return_value=None
        ), patch("kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock()), patch(
            "kali_mcp.db.manager.get_db", return_value=None
        ):
            res = await engine._execute_single_step(
                _step(id="s", module="cats/missing", args={}), {}
            )
        assert res["error"] == "module not found: cats/missing"

    async def test_execute_single_step_module_declares_no_tool(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._subst_target = "example.com"
        with patch(
            "kali_mcp.workflow.dag_executor.load_module", return_value={"inputs": {}}
        ), patch("kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock()), patch(
            "kali_mcp.db.manager.get_db", return_value=None
        ):
            res = await engine._execute_single_step(
                _step(id="s", module="cats/note", args={}), {}
            )
        assert res["error"] == "module cats/note declares no tool"

    async def test_execute_single_step_module_unknown_tool(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._subst_target = "example.com"
        with patch(
            "kali_mcp.workflow.dag_executor.load_module", return_value={"tool": "ghost"}
        ), patch(
            "kali_mcp.workflow.dag_executor._get_registry",
            return_value=_fake_registry({}),
        ), patch("kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock()), patch(
            "kali_mcp.db.manager.get_db", return_value=None
        ):
            res = await engine._execute_single_step(
                _step(id="s", module="cats/note", args={}), {}
            )
        assert res["error"] == "unknown tool"
        assert res["tool"] == "ghost"

    async def test_execute_single_step_scope_violation_raises(self):
        _clear_run_status()
        engine = PlaybookEngine()
        with patch(
            "kali_mcp.workflow.dag_executor.gate_step_args",
            new=MagicMock(side_effect=ScopeViolationError("out of scope")),
        ), patch("kali_mcp.db.manager.get_db", return_value=None):
            with pytest.raises(ScopeViolationError):
                await engine._execute_single_step(_step(id="s", tool="nmap", args={}), {})

    async def test_run_tool_step_output_mapping(self):
        _clear_run_status()
        call_log = []
        tools = {"nmap": _tool({"ports": []}, call_log=call_log)}
        engine = PlaybookEngine()
        engine._step_results["prior"] = {"host": "example.com"}
        with _env(tools=tools):
            res = await engine._run_tool_step(
                _step(
                    id="s",
                    tool="nmap",
                    args={"ports": "22"},
                    output_mapping={"target": "prior.host"},
                ),
                {},
            )
        assert call_log == [{"ports": "22", "target": "example.com"}]

    async def test_run_scope_check_direct(self):
        _clear_run_status()
        engine = PlaybookEngine()
        res = await engine._run_scope_check(
            _step(id="s", type="scope_check", args={"target": "a.com", "allowed": False}),
            {},
        )
        assert res == {
            "step": "s",
            "target": "a.com",
            "allowed": False,
            "scope_ok": False,
        }

    async def test_run_finding_correlation_direct(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["a"] = {
            "findings": [
                {"title": "T1", "target": "x.com", "tool": "nmap", "severity": "high", "evidence_ref": "e1"}
            ]
        }
        engine._step_results["b"] = {
            "findings": [
                {"title": "T1", "target": "x.com", "tool": "dnsx", "severity": "high", "evidence_ref": "e2"}
            ]
        }
        res = await engine._run_finding_correlation(
            _step(id="corr", type="finding_correlation", depends_on=["a", "b"], args={}),
            {},
        )
        assert res["total_observations"] == 2
        assert res["total_correlated"] == 1
        corr = res["correlated_findings"][0]
        assert corr["title"] == "T1"
        assert "dnsx" in corr["source_tools"]

    async def test_run_assessment_report_direct(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["corr"] = {
            "correlated_findings": [
                {"title": "T1", "severity": "high"},
                {"title": "T2", "severity": "low"},
            ]
        }
        res = await engine._run_assessment_report(
            _step(id="rep", type="assessment_report", depends_on=["corr"], args={}),
            {},
        )
        assert res["report"]["total_findings"] == 2
        assert res["report"]["severity_counts"]["high"] == 1
        assert res["report"]["severity_counts"]["low"] == 1

    async def test_run_custom_step_legacy_passthrough(self):
        _clear_run_status()
        engine = PlaybookEngine()
        res = await engine._run_custom_step(
            _step(id="s", type="custom", tool=None, args={}), {"playbook_name": "pb"}
        )
        assert res["status"] == "executed"
        assert res["type"] == "custom"

    async def test_run_custom_step_module_not_registered(self):
        _clear_run_status()
        engine = PlaybookEngine()
        with patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.has", return_value=False
        ):
            res = await engine._run_custom_step(
                _step(id="s", type="custom", tool="ghost.module", args={}),
                {"playbook_name": "pb"},
            )
        assert "module not registered: ghost.module" in res["error"]

    async def test_run_custom_step_module_registered(self):
        _clear_run_status()
        engine = PlaybookEngine()
        ctx = SimpleNamespace(playbook_name="pb")
        with patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.has", return_value=True
        ), patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.load_builtin_modules",
            return_value=[],
        ), patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.ModuleContext",
            return_value=ctx,
        ), patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.execute_async",
            new=AsyncMock(return_value={"custom": "done"}),
        ):
            res = await engine._run_custom_step(
                _step(id="s", type="custom", tool="my.mod", args={"module": "my.mod"}),
                {"playbook_name": "pb"},
            )
        assert res == {"custom": "done"}

    async def test_run_custom_step_module_error(self):
        _clear_run_status()
        engine = PlaybookEngine()
        with patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.has", return_value=True
        ), patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.load_builtin_modules",
            return_value=[],
        ), patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.ModuleContext",
            return_value=SimpleNamespace(playbook_name="pb"),
        ), patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.execute_async",
            new=AsyncMock(side_effect=ModuleError("boom")),
        ):
            res = await engine._run_custom_step(
                _step(id="s", type="custom", tool="my.mod", args={}),
                {"playbook_name": "pb"},
            )
        assert res["error"] == "boom"

    async def test_run_custom_step_scope_violation_re_raises(self):
        _clear_run_status()
        engine = PlaybookEngine()
        with patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.has", return_value=True
        ), patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.load_builtin_modules",
            return_value=[],
        ), patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.ModuleContext",
            return_value=SimpleNamespace(playbook_name="pb"),
        ), patch(
            "kali_mcp.workflow.dag_executor.modules_runtime.execute_async",
            new=AsyncMock(side_effect=ScopeViolationError("oops")),
        ):
            with pytest.raises(ScopeViolationError):
                await engine._run_custom_step(
                    _step(id="s", type="custom", tool="my.mod", args={}),
                    {"playbook_name": "pb"},
                )


# ── foreach direct ─────────────────────────────────────────────────────


class TestForeach:
    async def test_foreach_item_scope_violation_flags_item(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["dns"] = {"resolved_hosts": ["evil.com", "ok.com"]}
        call_log = []

        async def _exec(iter_step, state):
            call_log.append(iter_step.args["_foreach_item"])
            return {"step": iter_step.id, "ran": True}

        def _gate(args, *, step_id, tool_name=None):
            if args.get("target") == "evil.com":
                raise ScopeViolationError("evil.com not allowed")

        with patch(
            "kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock(side_effect=_gate)
        ), patch.object(engine, "_execute_single_step", _exec):
            res = await engine._run_foreach(
                _step(id="iter", tool="dnsx", foreach="dns.resolved_hosts", args={}),
                [_step(id="iter", tool="dnsx", foreach="dns.resolved_hosts", args={})],
                {},
            )
        items = res["foreach_results"]
        assert res["count"] == 2
        assert any(i.get("scope_violation") and "evil.com" in str(i.get("error")) for i in items)
        assert "ok.com" in call_log

    async def test_foreach_non_list_ref_wrapped(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["dns"] = {"resolved_hosts": "single.com"}
        call_log = []

        async def _exec(iter_step, state):
            call_log.append(iter_step.args["_foreach_item"])
            return {"step": iter_step.id, "ran": True}

        with patch(
            "kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock()
        ), patch.object(engine, "_execute_single_step", _exec):
            res = await engine._run_foreach(
                _step(id="iter", tool="dnsx", foreach="dns.resolved_hosts", args={}),
                [_step(id="iter", tool="dnsx", foreach="dns.resolved_hosts", args={})],
                {},
            )
        assert res["count"] == 1
        assert call_log == ["single.com"]

    async def test_foreach_empty_ref(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["dns"] = {"resolved_hosts": []}
        with patch(
            "kali_mcp.workflow.dag_executor.gate_step_args", new=MagicMock()
        ), patch.object(engine, "_execute_single_step", AsyncMock()):
            res = await engine._run_foreach(
                _step(id="iter", tool="dnsx", foreach="dns.resolved_hosts", args={}),
                [_step(id="iter", tool="dnsx", foreach="dns.resolved_hosts", args={})],
                {},
            )
        assert res["count"] == 0
        assert res["foreach_results"] == []


# ── helpers direct ─────────────────────────────────────────────────────


class TestHelpers:
    def test_topological_sort(self):
        _clear_run_status()
        engine = PlaybookEngine()
        steps = [
            _step(id="c", depends_on=["a", "b"]),
            _step(id="a"),
            _step(id="b", depends_on=["a"]),
        ]
        order = engine._topological_sort(steps)
        ids = [steps[i].id for i in order]
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")

    def test_compute_waves_cycle_fallback(self):
        _clear_run_status()
        engine = PlaybookEngine()
        # a <-> b cycle: no wave is ever "ready", so _compute_waves falls back
        # to scheduling all remaining steps in a single wave.
        steps = [
            _step(id="a", depends_on=["b"]),
            _step(id="b", depends_on=["a"]),
        ]
        waves = engine._compute_waves(steps)
        assert waves == [[0, 1]]

    def test_compute_waves(self):
        _clear_run_status()
        engine = PlaybookEngine()
        steps = [
            _step(id="a"),
            _step(id="b"),
            _step(id="c", depends_on=["a", "b"]),
            _step(id="d", depends_on=["c"]),
        ]
        waves = engine._compute_waves(steps)
        assert waves[0] == [0, 1]
        assert waves[1] == [2]
        assert waves[2] == [3]

    def test_compute_waves_all_independent_one_wave(self):
        _clear_run_status()
        engine = PlaybookEngine()
        steps = [_step(id="a"), _step(id="b"), _step(id="c")]
        waves = engine._compute_waves(steps)
        assert waves == [[0, 1, 2]]

    def test_evaluate_when_true_and_false(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["resolve"] = {"http_services_count": 3}
        assert engine._evaluate_when("resolve.http_services_count > 0") is True
        assert engine._evaluate_when("resolve.http_services_count > 5") is False
        assert engine._evaluate_when("resolve.http_services_count >= 3") is True
        assert engine._evaluate_when("resolve.http_services_count != 2") is True
        assert engine._evaluate_when("resolve.http_services_count < 3") is False

    def test_evaluate_when_missing_ref_false(self):
        _clear_run_status()
        engine = PlaybookEngine()
        assert engine._evaluate_when("missing.count > 0") is False
        assert engine._evaluate_when("garbage") is False

    def test_evaluate_when_string_comparison(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["scan"] = {"status": "completed"}
        assert engine._evaluate_when("scan.status == completed") is True
        assert engine._evaluate_when("scan.status == failed") is False

    def test_resolve_ref(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["s"] = {"a": {"b": 5}}
        assert engine._resolve_ref("s.a.b") == 5
        assert engine._resolve_ref("s.a") == {"b": 5}
        assert engine._resolve_ref("s.missing") is None
        assert engine._resolve_ref("missing.x") is None
        assert engine._resolve_ref("") is None
        assert engine._resolve_ref(None) is None

    def test_extract_findings(self):
        _clear_run_status()
        engine = PlaybookEngine()
        assert engine._extract_findings({"findings": [{"t": 1}]}) == [{"t": 1}]
        assert engine._extract_findings({"correlated_findings": [{"t": 2}]}) == [{"t": 2}]
        assert engine._extract_findings({"services": [{"t": 3}]}) == [{"t": 3}]
        assert engine._extract_findings({"assets": [{"t": 4}]}) == [{"t": 4}]
        assert engine._extract_findings({"result": {"findings": [{"t": 5}]}}) == [{"t": 5}]
        assert engine._extract_findings({"findings": [{"t": 6}, {"t": 7}]}) == [{"t": 6}, {"t": 7}]
        # bare list items are not themselves findings
        assert engine._extract_findings([{"t": 6}]) == []
        assert engine._extract_findings({"nothing": "here"}) == []
        assert engine._extract_findings("not-a-dict-or-list") == []

    def test_is_step_failure(self):
        _clear_run_status()
        engine = PlaybookEngine()
        assert engine._is_step_failure({"skipped": True}) is False
        assert engine._is_step_failure({"error": "x"}) is True
        assert engine._is_step_failure({"success": False}) is True
        assert engine._is_step_failure({"ok": True}) is False
        assert engine._is_step_failure("string") is False
        assert engine._is_step_failure(None) is False

    def test_depends_on_failed(self):
        _clear_run_status()
        engine = PlaybookEngine()
        engine._step_results["dep1"] = {"error": "x"}
        engine._step_results["dep2"] = {"ok": True}
        step = _step(id="s", depends_on=["dep1", "dep2"])
        assert engine._depends_on_failed(step, [step], 0) is True
        step2 = _step(id="s2", depends_on=["dep2"])
        assert engine._depends_on_failed(step2, [step2], 0) is False
        step3 = _step(id="s3", depends_on=["missing"])
        assert engine._depends_on_failed(step3, [step3], 0) is False

    def test_persist_state_in_memory_only(self):
        _clear_run_status()
        engine = PlaybookEngine()
        with patch("kali_mcp.db.manager.get_db", return_value=None):
            engine._persist_state("pb", {"status": "running", "completed_steps": [0]})
        assert de.RUN_STATUS["pb"] == {
            "status": "running",
            "completed_steps": [0],
        }

    def test_persist_state_calls_db(self):
        _clear_run_status()
        db = MagicMock()
        engine = PlaybookEngine()
        with patch("kali_mcp.db.manager.get_db", return_value=db):
            engine._persist_state("pb", {"status": "completed", "completed_steps": [0]})
        db.save_workflow_run.assert_called_once()
        args = db.save_workflow_run.call_args[0]
        assert args[0] == "pb"  # run_id
        assert args[1] == "pb"  # playbook_name
        assert args[2] == "completed"

    def test_get_status(self):
        _clear_run_status()
        assert de.PlaybookEngine().get_status("missing") is None
        de.RUN_STATUS["pb"] = {"status": "running"}
        assert PlaybookEngine().get_status("pb") == {"status": "running"}

    def test_cancel(self):
        _clear_run_status()
        assert PlaybookEngine().cancel("missing") is False
        de.RUN_STATUS["pb"] = {"status": "running"}
        assert PlaybookEngine().cancel("pb") is True
        assert de.RUN_STATUS["pb"]["status"] == "aborted"
        assert "finished_at" in de.RUN_STATUS["pb"]
