"""Tests for process-tree cleanup and the file_download tool."""

from __future__ import annotations

import asyncio

from kali_mcp.utils.process import kill_process_tree


class TestKillProcessTree:
    async def test_kill_running_process(self):
        proc = await asyncio.create_subprocess_exec(
            "sleep", "30", start_new_session=True
        )
        assert proc.returncode is None
        await kill_process_tree(proc)
        assert proc.returncode is not None  # died

    async def test_kill_without_own_session_would_hit_caller_group(self):
        """Documents WHY subprocesses must use start_new_session=True:
        without it, killpg targets the caller's own process group."""
        proc = await asyncio.create_subprocess_exec("true")
        await proc.wait()

    async def test_kill_already_dead_process_is_noop(self):
        proc = await asyncio.create_subprocess_exec("true")
        await proc.wait()
        await kill_process_tree(proc)  # must not raise

    async def test_kill_never_raises_on_invalid(self):
        class Fake:
            pid = 999_999_999
            returncode = None

        await kill_process_tree(Fake())  # must not raise

    async def test_child_processes_die(self):
        """A shell that spawned a sleeping child must not leak it.

        The subprocess gets its own session (start_new_session=True) exactly
        like the execution engine does — killpg then only touches its tree.
        """
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash", "-c", "sleep 3000 & wait", start_new_session=True
        )
        await asyncio.sleep(0.05)
        await kill_process_tree(proc)
        assert proc.returncode is not None

        # Give the kernel a moment, then verify the orphaned child is gone
        await asyncio.sleep(0.2)
        orphan = await asyncio.create_subprocess_exec(
            "pgrep",
            "-f",
            "sleep 3000",
            stdout=asyncio.subprocess.PIPE,
        )
        out, _ = await orphan.communicate()
        assert out.strip() == b"", f"orphaned child still alive: {out!r}"


class TestFileDownload:
    async def test_missing_path_rejected(self):
        from kali_mcp.tools.file_download import FileDownloadTool

        result = await FileDownloadTool().safe_execute({})
        assert result["isError"] is True

    async def test_nonexistent_file_rejected(self):
        from kali_mcp.tools.file_download import FileDownloadTool

        result = await FileDownloadTool().safe_execute({"server_path": "/no/such/file"})
        assert result["isError"] is True

    async def test_existing_file_yields_link(self, tmp_path):
        from kali_mcp.tools.file_download import FileDownloadTool

        f = tmp_path / "report.txt"
        f.write_text("findings here")
        result = await FileDownloadTool().safe_execute({"server_path": str(f)})
        assert result["isError"] is False
        text = result["content"][0]["text"]
        assert "curl" in text or "download" in text.lower()

    async def test_schema_has_required_fields(self):
        from kali_mcp.tools.file_download import FileDownloadTool

        schema = FileDownloadTool().input_schema()
        assert schema["required"] == ["server_path"]
