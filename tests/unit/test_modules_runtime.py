"""Tests for the internal-module runtime (Playbook Studio Phase 1)."""

from __future__ import annotations

import pytest

from kali_mcp.workflow import modules_runtime as mr
from kali_mcp.workflow.modules_runtime import (
    ModuleContext,
    ModuleError,
    execute,
    execute_async,
    has,
    list_modules,
    load_builtin_modules,
    register,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate module registrations per test."""
    mr.clear()
    yield
    mr.clear()


CTX = ModuleContext(assessment_id="assess_test", job_id="job_test")


class TestRegistration:
    def test_register_and_has(self):
        register("mod.ok", lambda ctx, **kw: {"ok": True})
        assert has("mod.ok")
        assert not has("mod.nope")

    def test_re_register_same_fn_is_idempotent(self):
        def fn(ctx, **kw):
            return {}

        register("mod.dup", fn)
        register("mod.dup", fn)  # no raise
        assert has("mod.dup")

    def test_conflicting_implementation_raises(self):
        register("mod.dup", lambda ctx, **kw: {})
        with pytest.raises(ModuleError):
            register("mod.dup", lambda ctx, **kw: {})

    def test_invalid_name_rejected(self):
        with pytest.raises(ModuleError):
            register("", lambda ctx: {})

    def test_noncallable_rejected(self):
        with pytest.raises(ModuleError):
            register("mod.bad", "not callable")

    def test_schemas_must_be_dicts(self):
        with pytest.raises(ModuleError):
            register("mod.bad_schema", lambda ctx, **kw: {}, input_schema=["x"])


class TestExecution:
    def test_execute_returns_dict(self):
        register("mod.add", lambda ctx, a, b: {"sum": a + b})
        assert execute("mod.add", CTX, {"a": 2, "b": 3}) == {"sum": 5}

    def test_unregistered_module_error(self):
        with pytest.raises(ModuleError, match="module not registered"):
            execute("mod.ghost", CTX, {})

    def test_non_dict_result_rejected(self):
        register("mod.bad", lambda ctx, **kw: [1, 2])
        with pytest.raises(ModuleError, match="must return a dict"):
            execute("mod.bad", CTX, {})

    def test_non_mapping_inputs_rejected(self):
        register("mod.ok", lambda ctx, **kw: {})
        with pytest.raises(ModuleError, match="mapping"):
            execute("mod.ok", CTX, "oops")  # type: ignore[arg-type]

    def test_required_input_enforced(self):
        register(
            "mod.req",
            lambda ctx, a: {"got": a},
            input_schema={"required": ["a"]},
        )
        with pytest.raises(ModuleError, match="missing required input"):
            execute("mod.req", CTX, {})
        assert execute("mod.req", CTX, {"a": 1}) == {"got": 1}

    def test_async_module_supported(self):
        async def fn(ctx, **kw):
            return {"async": True}

        register("mod.async", fn)
        assert execute("mod.async", CTX, {}) == {"async": True}

    async def test_execute_async_awaits_coroutines(self):
        async def fn(ctx, **kw):
            return {"value": 42}

        register("mod.await", fn)
        assert await execute_async("mod.await", CTX, {}) == {"value": 42}

    async def test_execute_async_unknown_module(self):
        with pytest.raises(ModuleError, match="module not registered"):
            await execute_async("mod.ghost2", CTX, {})


class TestListing:
    def test_list_modules_reports_schemas(self):
        register(
            "mod.b",
            lambda ctx, **kw: {},
            input_schema={"required": []},
            output_schema={"properties": {"x": {"type": "integer"}}},
        )
        register("mod.c", lambda ctx, **kw: {})
        items = list_modules()
        names = {m["name"] for m in items}
        assert names == {"mod.b", "mod.c"}
        by_name = {m["name"]: m for m in items}
        assert by_name["mod.b"]["has_output_schema"] is True
        assert by_name["mod.c"]["has_input_schema"] is False


class TestBuiltinLoading:
    def test_load_builtin_tolerates_partial_packages(self):
        # Builtin packages live under playbooks/modules; several may already
        # register implementations. Loading must never raise and must be
        # idempotent (second call no-ops).
        first = load_builtin_modules()
        second = load_builtin_modules()
        assert isinstance(first, list)
        assert second == []


def test_no_circular_import():
    """Engine and runtime import cleanly in any order."""
    from kali_mcp.workflow import dag_executor as de
    from kali_mcp.workflow.modules_runtime import register as _r  # noqa: F401

    assert hasattr(de, "MAX_ITERATIONS")
