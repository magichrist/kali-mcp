"""Interactive monitor module for the Kali MCP Server.

Aggregates live state from the session registry, execution engine, and health
monitor into a single snapshot that can be pushed to a CLI/TUI client over
SSE or queried directly via HTTP actions.

The monitor maintains a set of SSE client queues and broadcasts snapshots to
all connected clients whenever state changes (session connect/disconnect, job
start/end, or on-demand via the action endpoint).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from kali_mcp.models import utc_now_iso

logger = logging.getLogger("kali_mcp.monitor")


class Monitor:
    """Live monitor aggregating sessions, active jobs, and server health."""

    def __init__(
        self,
        session_registry: Any,
        engine: Any,
        health: Any,
    ) -> None:
        self.session_registry = session_registry
        self.engine = engine
        self.health = health
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    # ── SSE client management ──────────────────────────────────────

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a new SSE client queue. Returns the queue."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove an SSE client queue (client disconnected)."""
        self._clients.discard(q)

    async def broadcast(self, snapshot: dict[str, Any]) -> None:
        """Push a snapshot to all connected SSE clients.

        Queues that are full (slow clients) are dropped to avoid blocking
        the broadcast path.
        """
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for q in list(self._clients):
            try:
                q.put_nowait(snapshot)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._clients.discard(q)

    # ── Snapshot ───────────────────────────────────────────────────

    def build_snapshot(self) -> dict[str, Any]:
        """Build a complete live snapshot of server state."""
        return {
            "timestamp": utc_now_iso(),
            "sessions": self.session_registry.list_sessions(),
            "jobs": self.engine.get_active_jobs(),
            "health": self.health.get_status(),
        }

    # ── Actions ────────────────────────────────────────────────────

    async def kill_job(self, request_id: str) -> dict[str, Any]:
        """Kill a specific active execution by request ID.

        Terminates the subprocess (process tree) and broadcasts the new
        snapshot to all connected clients.
        """
        killed = await self.engine.kill_job(request_id)
        snapshot = self.build_snapshot()
        await self.broadcast(snapshot)
        return {
            "action": "kill_job",
            "request_id": request_id,
            "killed": killed,
        }

    async def force_cleanup(self) -> dict[str, Any]:
        """Force cleanup all tracked executions and broadcast the snapshot."""
        cleaned = self.engine.force_cleanup()
        snapshot = self.build_snapshot()
        await self.broadcast(snapshot)
        return {
            "action": "force_cleanup",
            "cleaned": cleaned,
        }

    def get_snapshot(self) -> dict[str, Any]:
        """Synchronous snapshot getter (for non-async callers)."""
        return self.build_snapshot()
