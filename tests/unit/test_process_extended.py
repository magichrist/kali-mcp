"""Unit tests for utils/process.py (kill_process_tree edge cases)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kali_mcp.utils.process import kill_process_tree


class TestKillProcessTree:
    @pytest.mark.asyncio
    async def test_already_finished_process(self) -> None:
        proc = MagicMock()
        proc.returncode = 0
        # Should not raise and should not attempt to kill
        await kill_process_tree(proc)
        proc.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_group_kill(self) -> None:
        proc = MagicMock()
        proc.returncode = None
        proc.pid = 1234
        with patch("kali_mcp.utils.process.os.getpgid", return_value=1234), patch(
            "kali_mcp.utils.process.os.killpg"
        ) as mock_killpg, patch(
            "kali_mcp.utils.process.asyncio.wait_for", return_value=None
        ):
            await kill_process_tree(proc)
            mock_killpg.assert_called_once_with(1234, __import__("signal").SIGKILL)

    @pytest.mark.asyncio
    async def test_killpg_falls_back_to_proc_kill(self) -> None:
        proc = MagicMock()
        proc.returncode = None
        proc.pid = 1234
        with patch(
            "kali_mcp.utils.process.os.getpgid", side_effect=PermissionError
        ), patch("kali_mcp.utils.process.asyncio.wait_for", return_value=None):
            await kill_process_tree(proc)
            proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_timeout_swallowed(self) -> None:
        proc = MagicMock()
        proc.returncode = None
        proc.pid = 1234
        with patch(
            "kali_mcp.utils.process.os.getpgid", return_value=1234
        ), patch(
            "kali_mcp.utils.process.os.killpg"
        ), patch(
            "kali_mcp.utils.process.asyncio.wait_for", side_effect=TimeoutError
        ):
            # Should not raise
            await kill_process_tree(proc)

    @pytest.mark.asyncio
    async def test_unexpected_error_swallowed(self) -> None:
        proc = MagicMock()
        proc.returncode = None
        proc.pid = 1234
        with patch(
            "kali_mcp.utils.process.os.getpgid", side_effect=RuntimeError("boom")
        ):
            await kill_process_tree(proc)
