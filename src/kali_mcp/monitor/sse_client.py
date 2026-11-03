"""SSE client for the monitor TUI.

Connects to ``GET /monitor/stream`` on the Kali MCP Server and yields live
snapshots as they arrive. Slow consumers have their snapshots dropped
(queue full) so the reader never blocks.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx


class SseClient:
    """Reads SSE snapshots from the monitor stream endpoint.

    Usage::

        client = SseClient("http://localhost:8399/monitor/stream")
        await client.connect()
        snapshot = await client.next_snapshot()  # blocks until next event
    """

    def __init__(self, url: str, max_queue: int = 10) -> None:
        self.url = url
        self._max_queue = max_queue
        self._snapshot: dict[str, Any] | None = None
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=max_queue)
        self._task: asyncio.Task | None = None
        self._closed = False

    async def connect(self) -> None:
        """Connect to the SSE stream and start reading in the background."""
        self._task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        while not self._closed:
            try:
                async with httpx.AsyncClient(timeout=None) as http, http.stream(
                    "GET", self.url
                ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if self._closed:
                                return
                            if line.startswith("data: "):
                                try:
                                    payload = json.loads(line[len("data: ") :])
                                except json.JSONDecodeError:
                                    continue
                                self._snapshot = payload
                                try:
                                    self._queue.put_nowait(payload)
                                except asyncio.QueueFull:
                                    # Slow consumer — drop this snapshot
                                    try:
                                        self._queue.get_nowait()
                                    except asyncio.QueueEmpty:
                                        pass
                                    self._queue.put_nowait(payload)
            except (httpx.ConnectError, httpx.ReadError, OSError):
                # Server went down — retry after a short pause
                await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                return

    async def next_snapshot(self) -> dict[str, Any] | None:
        """Wait for and return the next snapshot from the stream."""
        item = await self._queue.get()
        return item

    def get_latest_snapshot(self) -> dict[str, Any] | None:
        """Return the most recent snapshot without waiting."""
        return self._snapshot

    async def close(self) -> None:
        """Close the SSE connection."""
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
