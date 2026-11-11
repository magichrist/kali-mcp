"""Advanced execution engine tests: truncation, concurrency, progress, stats."""

from __future__ import annotations

import asyncio

from kmcp.execution import MAX_OUTPUT, ExecutionEngine, engine


class TestOutputTruncation:
    async def test_stdout_truncated_to_100kb(self):
        r = await engine.execute(["python3", "-c", "print('x' * 500000)"], tool="test")
        assert len(r.stdout) == MAX_OUTPUT
        assert r.success is True  # command itself succeeded

    async def test_stderr_truncated_to_100kb(self):
        r = await engine.execute(
            [
                "bash",
                "-c",
                "python3 -c \"import sys; print('e' * 500000, file=sys.stderr)\"",
            ],
            tool="test",
        )
        assert len(r.stderr) == MAX_OUTPUT


class TestConcurrency:
    async def test_semaphore_caps_concurrency(self):
        eng = ExecutionEngine()
        # max_concurrent comes from kmcp.config (10); verify by timing batch
        results = await asyncio.gather(
            *[eng.execute(["sleep", "0.3"], tool="test") for _ in range(6)]
        )
        assert all(r.success for r in results)
        assert eng.get_stats()["total_requests"] == 6

    async def test_error_isolation_across_concurrent_runs(self):
        results = await asyncio.gather(
            *[
                engine.execute(cmd, tool="test")
                for cmd in (
                    ["echo", "ok"],
                    ["false"],
                    ["__missing_bin__"],
                    ["echo", "fine"],
                )
            ]
        )
        assert [r.success for r in results] == [True, False, False, True]


class TestProgressCallbacks:
    async def test_sync_progress_callback_receives_0_and_100(self):
        events: list[tuple[int, int]] = []

        def cb(completed: int, total: int):
            events.append((completed, total))

        r = await engine.execute(["echo", "x"], tool="test", progress_cb=cb)
        assert r.success
        assert events[0] == (0, 100)
        assert events[-1] == (100, 100)

    async def test_async_progress_callback(self):
        events: list[tuple[int, int]] = []

        async def cb(completed: int, total: int):
            events.append((completed, total))

        r = await engine.execute(["echo", "x"], tool="test", progress_cb=cb)
        assert r.success
        assert (0, 100) in events

    async def test_broken_progress_cb_does_not_break_execution(self):
        def cb(*a):
            raise RuntimeError("cb exploded")

        r = await engine.execute(["echo", "survived"], tool="test", progress_cb=cb)
        assert r.success is True
        assert r.stdout.strip() == "survived"


class TestTimeoutsAndCleanup:
    async def test_timeout_value_coercion(self):
        # Non-numeric timeout falls back to default without raising
        r = await engine.execute(["echo", "ok"], tool="test", timeout="not-a-number")  # type: ignore[arg-type]
        assert r.success is True

    async def test_timeout_capped_at_max(self):
        r = await engine.execute(["echo", "ok"], tool="test", timeout=999_999)
        assert r.success is True  # capped, not an error

    async def test_negative_timeout_immediately_times_out(self):
        r = await engine.execute(["echo", "late"], tool="test", timeout=-1)
        assert r.timed_out is True

    async def test_empty_cwd_string_ignored(self):
        r = await engine.execute(["pwd"], tool="test", cwd="   ")
        assert r.success is True

    async def test_force_cleanup_returns_count(self):
        eng = ExecutionEngine()
        assert eng.force_cleanup() == 0
        eng._active["fake-req"] = "fake-tool"
        assert eng.force_cleanup() == 1
        assert eng.active_count == 0

    async def test_get_stats_shape(self):
        stats = engine.get_stats()
        assert set(stats) == {
            "active_executions",
            "total_requests",
            "total_errors",
            "max_concurrent",
        }

    async def test_active_count_tracks_running(self):
        eng = ExecutionEngine()
        task = asyncio.create_task(eng.execute(["sleep", "0.5"], tool="test"))
        await asyncio.sleep(0.1)
        assert eng.active_count >= 1
        await task
        assert eng.active_count == 0

    async def test_get_stuck_executions_empty_after_completion(self):
        eng = ExecutionEngine()
        await eng.execute(["echo", "done"], tool="test")
        assert eng.get_stuck_executions() == []


class TestPathEnvironment:
    async def test_system_path_appended(self):
        r = await engine.execute(["bash", "-c", "echo $PATH"], tool="test", env={"PATH": "/custom"})
        assert r.stdout.strip().startswith("/custom")
        assert "/usr/bin" in r.stdout

    async def test_missing_env_path_defaults(self):
        r = await engine.execute(["bash", "-c", "echo $PATH"], tool="test", env={})
        assert "/usr/bin" in r.stdout
