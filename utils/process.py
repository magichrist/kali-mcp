"""Process cleanup utilities."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

logger = logging.getLogger("kali_mcp.process")


async def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill a process. Never raises."""
    try:
        if proc.returncode is not None:
            return

        # Try process group kill first
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass

        # Wait briefly for it to die
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

    except Exception as e:
        logger.warning("Error killing process %s: %s", getattr(proc, 'pid', '?'), e)
