"""Extra coverage tests for the module runtime (workflow/modules_runtime.py).

Targets the async execution paths, required-input schema edge case, and the
load_builtin_modules tolerance branches (missing __path__, import failures,
and modules without a register hook).
"""

from __future__ import annotations

import asyncio
import types

import pytest

from kali_mcp.workflow import modules_runtime as mr
from kali_mcp.workflow.modules_runtime import (
    ModuleContext,
    ModuleError,
    execute,
    execute_async,
    register,
)


CTX = ModuleContext(assessment_id="assess_test", job_id="job_test")


class TestExecuteSync:
    def test_coroutine_function_runs_via_asyncio_run(self):
        # No event loop is running in a sync test, so execute() falls back
        # to asyncio.run() for coroutine results.
        async def coro_fn(ctx, **kw):
            return {"coro": True}

        register("mod.coro", coro_fn)
        assert execute("mod.coro", CTX, {}) == {"coro": True}


class TestExecuteAsync:
    def test_non_mapping_inputs_rejected(self):
        register("mod.ok", lambda ctx, **kw: {})
        with pytest.raises(ModuleError, match="mapping"):
            # execute_async is async-aware but the inputs check runs first.
            asyncio.run(execute_async("mod.ok", CTX, "oops"))  # type: ignore[arg-type]

    def test_required_input_enforced_from_schema(self):
        register(
            "mod.req",
            lambda ctx, a: {"got": a},
            input_schema={"required": ["a"]},
        )
        with pytest.raises(ModuleError, match="missing required input"):
            asyncio.run(execute_async("mod.req", CTX, {}))
        assert asyncio.run(execute_async("mod.req", CTX, {"a": 1})) == {"got": 1}

    def test_non_dict_result_rejected(self):
        register("mod.bad", lambda ctx, **kw: [1, 2])
        with pytest.raises(ModuleError, match="must return a dict"):
            asyncio.run(execute_async("mod.bad", CTX, {}))


class TestCheckRequiredEdge:
    def test_required_schema_not_a_list_is_ignored(self):
        # required is a string -> _check_required returns early (no error).
        register(
            "mod.weird",
            lambda ctx: {"ok": True},
            input_schema={"required": "not-a-list"},
        )
        assert execute("mod.weird", CTX, {}) == {"ok": True}


class TestLoadBuiltinModules:
    def test_pkg_path_none_returns_empty(self, monkeypatch):
        import kali_mcp.playbooks.modules as modules_pkg

        orig_path = modules_pkg.__path__
        modules_pkg.__path__ = None  # type: ignore[assignment]
        try:
            mr.clear()
            result = mr.load_builtin_modules()
            assert result == []
        finally:
            modules_pkg.__path__ = orig_path

    def test_import_failure_is_tolerated(self, monkeypatch):
        monkeypatch.setattr(
            mr.importlib,
            "import_module",
            lambda name: (_ for _ in ()).throw(ImportError("boom")),
        )
        # iter_modules is left real; every real module import fails -> skipped.
        mr.clear()
        result = mr.load_builtin_modules()
        assert result == []

    def test_module_without_register_is_skipped(self, monkeypatch):
        fake_mod = types.ModuleType("kali_mcp.playbooks.modules.noreg")
        # Deliberately no `register` attribute -> the `continue` branch.
        monkeypatch.setattr(mr.importlib, "import_module", lambda name: fake_mod)
        mr.clear()
        result = mr.load_builtin_modules()
        assert result == []
        assert not mr.has("noreg")
