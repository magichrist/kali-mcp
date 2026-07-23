"""Process cleanup utilities."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

logger = logging.getLogger("kali_mcp.process")


async def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill a process and its entire process group."""
    try:
        if proc.returncode is not None:
            return

        # Try to kill the process group
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError) as e:
            logger.warning("Failed to kill process group %d: %s", proc.pid, e)
            # Fallback to killing just the process
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass

        if proc.returncode is None:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError) as e:
                logger.warning("Failed to force-kill process group %d: %s", proc.pid, e)
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Process %d did not terminate after SIGKILL", proc.pid)

        if proc.returncode is None:
            logger.warning("Process %d could not be killed (may be zombie)", proc.pid)

    except Exception as e:
        logger.warning("Error killing process tree: %s", e)
