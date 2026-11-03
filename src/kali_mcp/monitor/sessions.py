"""MCP client session registry for the interactive monitor.

Tracks active MCP client sessions: when they connect, their last activity,
and client information from the MCP ``initialize`` handshake. State lives
in-memory and resets on server restart (by design).
"""

from __future__ import annotations

import threading
from typing import Any

from kali_mcp.models import utc_now_iso


class SessionRegistry:
    """Thread-safe registry of active MCP client sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def on_connect(self, session_id: str, client_info: dict[str, Any] | None = None) -> None:
        """Record that a new MCP client session has connected."""
        now = utc_now_iso()
        with self._lock:
            self._sessions[session_id] = {
                "session_id": session_id,
                "connected_at": now,
                "last_activity": now,
                "client_info": client_info or {},
            }

    def on_activity(self, session_id: str) -> None:
        """Update the last-activity timestamp for an existing session."""
        now = utc_now_iso()
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id]["last_activity"] = now

    def on_disconnect(self, session_id: str) -> None:
        """Remove a session from the registry (client disconnected)."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return a copy of all known sessions, newest-created first."""
        with self._lock:
            sessions = list(self._sessions.values())
        sessions.sort(key=lambda s: s["connected_at"], reverse=True)
        return sessions

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return a single session by ID, or None if unknown."""
        with self._lock:
            return self._sessions.get(session_id)

    def count(self) -> int:
        """Return the number of currently tracked sessions."""
        with self._lock:
            return len(self._sessions)

    def clear(self) -> None:
        """Remove all sessions (used in tests / forced reset)."""
        with self._lock:
            self._sessions.clear()


# Global session registry shared by the server and the monitor module.
session_registry = SessionRegistry()
