"""Unit tests for shell nodes in the DAG workflow engine.

Covers: loader acceptance (type=shell + command/inputs/filter fields),
placeholder resolution (playbook inputs, upstream outputs, literals),
filter extraction (named groups, capture groups, first_only), and the
scope gate hook on resolved inputs.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kali_mcp.models import ExecutionResult
from kali_mcp.workflow.dag_executor import PlaybookEngine
from kali_mcp.workflow.scope_gate import ScopeViolationError
from kali_mcp.workflow.validator import validate_playbook
from kali_mcp.workflow.yaml_loader import (
    PlaybookDefinition,
    PlaybookError,
    StepDefinition,
    load_playbook,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── loader ─────────────────────────────────────────────────────────────


def test_loader_accepts_shell_nodes() -> None:
    defn = load_playbook(
        {
            "name": "sh",
            "version": "1.0.0",
            "inputs": {
                "ip": {"type": "string", "required": True, "source": "operator"},
            },
            "steps": [
                {
                    "id": "probe",
                    "type": "shell",
                    "command": "nmap {ip} -sn -p80",
                    "inputs": {"ip": "{{ip}}"},
                    "filter": {
                        "type": "grep",
                        "pattern": "Host.*(?P<host>[0-9.]+)",
                        "first_only": True,
                    },
                    "depends_on": [],
                }
            ],
        }
    )
    step = defn.steps[0]
    assert step.type == "shell"
    assert step.command == "nmap {ip} -sn -p80"
    assert step.inputs == {"ip": "{{ip}}"}
    assert step.filter["pattern"] == "Host.*(?P<host>[0-9.]+)"


def test_loader_rejects_unknown_step_type() -> None:
    with pytest.raises(PlaybookError):
        load_playbook(
            {"name": "x", "steps": [{"id": "s", "type": "not_a_type"}]},
        )


# ── shell step execution ───────────────────────────────────────────────


def _make_engine(playbook_inputs: dict[str, Any] | None = None) -> PlaybookEngine:
    eng = PlaybookEngine()
    eng._subst_target = (playbook_inputs or {}).get("targets")
    eng._playbook_inputs = {
        k: v
        for k, v in (playbook_inputs or {}).items()
        if isinstance(v, (str, int, float)) or (isinstance(v, list) and v)
    }
    return eng


def _fake_result(stdout: str, exit_code: int = 0) -> ExecutionResult:
    return ExecutionResult(
        tool="shell_command",
        command="x",
        stdout=stdout,
        stderr="",
        exit_code=exit_code,
        success=exit_code == 0,
        timed_out=False,
        duration=0.01,
        start_time="",
        end_time="",
    )


def test_shell_placeholder_from_playbook_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """`{ip}` filled from playbook-level input provided by the agent LLM."""
    eng = _make_engine({"ip": "192.168.1.1"})
    step = StepDefinition(
        id="probe",
        type="shell",
        command="nmap {ip} -sn -p80",
        inputs={},
        filter={},
    )

    async def fake_execute(cmd: Any, **kwargs: Any) -> ExecutionResult:
        assert str(cmd) == "nmap 192.168.1.1 -sn -p80"
        return _fake_result("nmap done: 1 IP up")

    monkeypatch.setattr(
        "kali_mcp.execution.engine.execute",
        fake_execute,
    )
    res = _run(eng._run_shell_step(step, {}))
    assert res["command"] == "nmap 192.168.1.1 -sn -p80"
    assert "error" not in res


def test_shell_placeholder_from_upstream_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """`{ip}` resolved from a prior node's extracted output via {{node.field}}."""
    eng = _make_engine()
    eng._step_results["discovery"] = {"ip": "192.168.1.7"}
    step = StepDefinition(
        id="scan",
        type="shell",
        command="nmap {ip}",
        depends_on=["discovery"],
        inputs={"ip": "{{discovery.ip}}"},
    )

    async def fake_execute(cmd: Any, **kwargs: Any) -> ExecutionResult:
        assert str(cmd) == "nmap 192.168.1.7"
        return _fake_result("ok")

    monkeypatch.setattr("kali_mcp.execution.engine.execute", fake_execute)
    res = _run(eng._run_shell_step(step, {}))
    assert res["command"] == "nmap 192.168.1.7"


def test_shell_missing_input_is_clean_failure() -> None:
    eng = _make_engine()
    step = StepDefinition(
        id="scan",
        type="shell",
        command="nmap {ip}",
        inputs={"ip": "{{ip}}"},
    )
    res = _run(eng._run_shell_step(step, {}))
    assert res["error"].startswith("unresolved placeholder")
    assert "ip" in res["error"]


def test_shell_command_not_executed_when_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing inputs must short-circuit before any command runs."""
    eng = _make_engine()
    step = StepDefinition(id="s", type="shell", command="nmap {ip}")
    called = {"n": 0}

    async def fake_execute(cmd: Any, **kwargs: Any) -> ExecutionResult:
        called["n"] += 1
        return _fake_result("")

    monkeypatch.setattr("kali_mcp.execution.engine.execute", fake_execute)
    res = _run(eng._run_shell_step(step, {}))
    assert called["n"] == 0
    assert "unresolved" in res["error"]


def test_shell_filter_named_groups_become_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    eng = _make_engine()
    stdout = "Nmap scan report for 192.168.1.10\nHost is up (0.001s latency).\nNmap scan report for 192.168.1.11"
    step = StepDefinition(
        id="disc",
        type="shell",
        command="nmap -sn 192.168.1.0/24",
        inputs={},
        filter={"type": "grep", "pattern": r"Nmap scan report for (?P<ip>[0-9.]+)"},
    )

    async def fake_execute(cmd: Any, **kwargs: Any) -> ExecutionResult:
        return _fake_result(stdout)

    monkeypatch.setattr("kali_mcp.execution.engine.execute", fake_execute)
    res = _run(eng._run_shell_step(step, {}))
    assert res["ip"] == ["192.168.1.10", "192.168.1.11"]
    assert res["match_count"] == 2
    assert "Nmap scan report for 192.168.1.10" in res["filtered_lines"]


def test_shell_filter_first_only(monkeypatch: pytest.MonkeyPatch) -> None:
    eng = _make_engine()
    step = StepDefinition(
        id="disc",
        type="shell",
        command="nmap {ip}",
        inputs={"ip": "127.0.0.1"},
        filter={
            "type": "grep",
            "pattern": r"Nmap scan report for (?P<host>[0-9.]+)",
            "first_only": True,
        },
    )

    async def fake_execute(cmd: Any, **kwargs: Any) -> ExecutionResult:
        return _fake_result("Nmap scan report for 1.1.1.1\nNmap scan report for 2.2.2.2")

    monkeypatch.setattr("kali_mcp.execution.engine.execute", fake_execute)
    res = _run(eng._run_shell_step(step, {}))
    assert res["host"] == "1.1.1.1"


def test_shell_filter_first_only_no_matches_is_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """first_only with zero matches must not raise IndexError (bug found live)."""
    eng = _make_engine()
    step = StepDefinition(
        id="probe",
        type="shell",
        command="echo {ip}",
        inputs={"ip": "127.0.0.1 127.0.0.2"},
        filter={
            "type": "grep",
            "pattern": r"probing (?P<who>[0-9.]+) and (?P<dom>[0-9a-z.-]+)",
            "first_only": True,
        },
    )

    async def fake_execute(cmd: Any, **kwargs: Any) -> ExecutionResult:
        return _fake_result("probing 127.0.0.1 127.0.0.2 and demo.example.com\n")

    monkeypatch.setattr("kali_mcp.execution.engine.execute", fake_execute)
    res = _run(eng._run_shell_step(step, {}))
    assert res.get("match_count") == 0
    assert res["who"] == [] and res["dom"] == []


def test_shell_filter_unnamed_capture_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    eng = _make_engine()
    step = StepDefinition(
        id="s",
        type="shell",
        command="echo hi",
        inputs={},
        filter={"type": "grep", "pattern": r"(h)(i)", "first_only": True},
    )

    async def fake_execute(cmd: Any, **kwargs: Any) -> ExecutionResult:
        return _fake_result("hi")

    monkeypatch.setattr("kali_mcp.execution.engine.execute", fake_execute)
    res = _run(eng._run_shell_step(step, {}))
    assert res["match_1"] == "h"
    assert res["match_2"] == "i"


def test_shell_scope_violation_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolved input values hit the scope gate — out-of-scope never executes."""
    eng = _make_engine()
    eng._playbook_inputs = {}
    step = StepDefinition(
        id="s",
        type="shell",
        command="nmap {ip}",
        inputs={"ip": "127.0.0.1"},
    )
    from kali_mcp.workflow import dag_executor as de

    def vainless_scope(args: dict, **kw: Any) -> None:
        raise ScopeViolationError("blocked")

    monkeypatch.setattr(de, "gate_step_args", vainless_scope)
    with pytest.raises(ScopeViolationError):
        _run(eng._run_shell_step(step, {}))


def test_shell_refs_from_args_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """args.timeout flows to the execution engine; output_mapping refs work."""
    eng = _make_engine({"ip": "127.0.0.1"})
    seen: dict[str, Any] = {}
    step = StepDefinition(
        id="s",
        type="shell",
        command="echo {ip}",
        inputs={},
        args={"timeout": 7},
    )

    async def fake_execute(cmd: Any, **kwargs: Any) -> ExecutionResult:
        seen.update(kwargs, cmd=str(cmd))
        return _fake_result("done")

    monkeypatch.setattr("kali_mcp.execution.engine.execute", fake_execute)
    res = _run(eng._run_shell_step(step, {}))
    assert seen["timeout"] == 7
    assert res["exit_code"] == 0


# ── validation ─────────────────────────────────────────────────────────


def test_validate_shell_step_ok() -> None:
    defn = PlaybookDefinition(
        name="sh",
        version="1.0.0",
        inputs={"ip": {"type": "string", "required": True, "source": "operator"}},
        execution={},
        raw={},
        steps=[
            StepDefinition(
                id="s",
                type="shell",
                command="nmap {ip}",
                inputs={"ip": "{{ip}}"},
                filter={"type": "grep", "pattern": r"(?P<ip>[0-9.]+)"},
            )
        ],
    )
    findings = validate_playbook(defn)
    errs = [f for f in findings if f["severity"] == "error"]
    assert errs == []


def test_validate_shell_missing_command_is_error() -> None:
    defn = PlaybookDefinition(
        name="sh",
        version="1.0.0",
        inputs={},
        execution={},
        raw={},
        steps=[StepDefinition(id="s", type="shell")],
    )
    findings = validate_playbook(defn)
    fields = [f["field"] for f in findings if f["severity"] == "error"]
    assert "command" in fields


def test_validate_shell_bad_pattern_is_error() -> None:
    defn = PlaybookDefinition(
        name="sh",
        version="1.0.0",
        inputs={},
        execution={},
        raw={},
        steps=[
            StepDefinition(
                id="s",
                type="shell",
                command="echo x",
                filter={"type": "grep", "pattern": "(?P<broken>[a-"},
            )
        ],
    )
    findings = validate_playbook(defn)
    assert any(f["field"] == "filter.pattern" for f in findings)
