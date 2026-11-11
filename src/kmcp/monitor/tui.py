"""Interactive CLI/TUI for the Kali MCP monitor.

Female cyberspace aesthetic — gummy amber (#FFBF00), magenta-pink (#FF69B4),
and cyberspace cyan (#18FFFF) on a deep dark background. Built with Rich for
rendering and a background thread for non-blocking stdin.

Connects to the server's ``GET /monitor/stream`` SSE endpoint and renders a
live dashboard with three panels:

  * Connected Users — active MCP client sessions
  * Running Jobs — active tool executions (nmap, sqlmap, etc.)
  * Server Health — uptime, memory, request counts, tool inventory

Keybindings:

  * ``q`` — quit
  * ``r`` — force a refresh of the display
  * ``f`` — force cleanup all tracked executions
  * ``k`` — kill a job (press ``k`` twice quickly to kill the selected item)
  * ``←`` / ``→`` — switch between sessions and jobs panels
  * ``↑`` / ``↓`` — move selection within the active panel
"""

from __future__ import annotations

import asyncio
import os
import sys
import termios
import threading
import time
import tty
from typing import Any

import httpx
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from kmcp.monitor.sse_client import SseClient

# ═════════════════════════════════════════════════════════════════════════════
# Cyberspace color palette (dark-background friendly)
# ═════════════════════════════════════════════════════════════════════════════

CYBERSPACE_CYAN = "#18FFFF"  # bright electric cyan — headers / primary text
GUMMY_AMBER = "#FFBF00"  # gummy amber — highlights / values / jobs
GUMMY_PINK = "#FF69B4"  # hot pink / magenta — alerts / actions / borders
GUMMY_LIGHT_PINK = "#FFB6C1"  # soft pink — secondary text
DARK_PANEL_BG = "#0a0a0f"  # near-black panel background — deep cyberspace
SELECTED_BG = "#2a2a3a"  # highlighted row background

# ═════════════════════════════════════════════════════════════════════════════
# Selection state helpers
# ═════════════════════════════════════════════════════════════════════════════

PANEL_SESSIONS = 0  # left panel — connected users
PANEL_JOBS = 1  # right panel — running jobs


def _panel_name(panel: int) -> str:
    return "Sessions" if panel == PANEL_SESSIONS else "Jobs"


# ═════════════════════════════════════════════════════════════════════════════
# Panel builders (with optional row highlight)
# ═════════════════════════════════════════════════════════════════════════════


def _sessions_panel(
    sessions: list[dict[str, Any]],
    selected_index: int = -1,
    active: bool = False,
) -> Panel:
    table = Table(show_header=True, header_style=f"bold {GUMMY_AMBER}", expand=True)
    table.add_column("Session ID", style=CYBERSPACE_CYAN, width=14)
    table.add_column("Connected At", style=GUMMY_LIGHT_PINK, width=20)
    table.add_column("Last Activity", style=GUMMY_LIGHT_PINK, width=20)
    table.add_column("Client", style=CYBERSPACE_CYAN, width=26)

    for i, s in enumerate(sessions):
        ci = s.get("client_info", {}) or {}
        client_str = f"{ci.get('name', '-')}/{ci.get('version', '-')}"
        is_sel = active and i == selected_index
        row_style = f"bold {SELECTED_BG}" if is_sel else None
        table.add_row(
            str(s.get("session_id", "-")),
            str(s.get("connected_at", "-")),
            str(s.get("last_activity", "-")),
            client_str,
            style=row_style,
        )

    return Panel(
        table,
        title=_styled_text("Connected Users", f"bold {GUMMY_PINK}"),
        border_style=GUMMY_PINK if active else "dim",
        title_align="left",
    )


def _jobs_panel(
    jobs: list[dict[str, Any]],
    selected_index: int = -1,
    active: bool = False,
) -> Panel:
    table = Table(show_header=True, header_style=f"bold {GUMMY_AMBER}", expand=True)
    table.add_column("Request ID", style=CYBERSPACE_CYAN, width=14)
    table.add_column("Tool", style=CYBERSPACE_CYAN, width=16)
    table.add_column("Elapsed (s)", style=GUMMY_AMBER, width=12, justify="right")

    for i, j in enumerate(jobs):
        is_sel = active and i == selected_index
        row_style = f"bold {SELECTED_BG}" if is_sel else None
        table.add_row(
            str(j.get("request_id", "-")),
            str(j.get("tool", "-")),
            f"{j.get('elapsed_seconds', 0):.1f}",
            style=row_style,
        )

    return Panel(
        table,
        title=_styled_text("Running Jobs", f"bold {GUMMY_PINK}"),
        border_style=GUMMY_PINK if active else "dim",
        title_align="left",
    )


def _styled_text(content: str, style: str) -> Text:
    return Text(content, style=style)


def _health_panel(health: dict[str, Any]) -> Panel:
    grid = Table.grid(padding=(0, 1), expand=True)
    grid.add_column(style=CYBERSPACE_CYAN, width=24)
    grid.add_column(style=GUMMY_LIGHT_PINK)

    grid.add_row("Status:", str(health.get("status", "-")))
    grid.add_row("Uptime:", f"{health.get('uptime_seconds', 0):.1f}s")
    grid.add_row("Active Executions:", str(health.get("active_executions", 0)))
    grid.add_row("Total Requests:", str(health.get("total_requests", 0)))
    grid.add_row("Total Errors:", str(health.get("total_errors", 0)))
    grid.add_row("Tools Registered:", str(health.get("tools_registered", 0)))
    grid.add_row("Memory:", f"{health.get('memory_mb', 0):.1f} MB")

    return Panel(
        grid,
        title=_styled_text("Server Health", f"bold {GUMMY_PINK}"),
        border_style=GUMMY_PINK,
        title_align="left",
    )


def build_layout(
    snapshot: dict[str, Any] | None,
    status_msg: str = "",
    panel: int = PANEL_SESSIONS,
    index: int = -1,
) -> Layout:
    """Build the full dashboard layout from a monitor snapshot."""
    layout = Layout()

    ts = snapshot.get("timestamp", "-") if snapshot else "-"
    header_text = Text(
        f"Kali MCP Monitor — {ts}",
        style=f"bold {CYBERSPACE_CYAN} on {DARK_PANEL_BG}",
    )
    if status_msg:
        header_text.append("  |  ", style=GUMMY_LIGHT_PINK)
        header_text.append(status_msg, style=GUMMY_AMBER)
    header = Panel(header_text, border_style=GUMMY_PINK, style=DARK_PANEL_BG)

    layout.split(
        Layout(header, name="top", size=3),
        Layout(name="middle", ratio=1),
        Layout(name="bottom", ratio=1),
    )

    sessions = snapshot.get("sessions", []) if snapshot else []
    jobs = snapshot.get("jobs", []) if snapshot else []

    sessions_active = panel == PANEL_SESSIONS
    jobs_active = panel == PANEL_JOBS

    # Clamp index to valid range for the active panel
    if sessions_active and index >= len(sessions):
        index = max(len(sessions) - 1, 0)
    if jobs_active and index >= len(jobs):
        index = max(len(jobs) - 1, 0)

    layout["middle"].split_row(
        Layout(
            _sessions_panel(sessions, index if sessions_active else -1, sessions_active),
            name="sessions",
        ),
        Layout(
            _jobs_panel(jobs, index if jobs_active else -1, jobs_active),
            name="jobs",
        ),
    )
    layout["bottom"].update(_health_panel(snapshot.get("health", {}) if snapshot else {}))

    return layout


# ═════════════════════════════════════════════════════════════════════════════
# HTTP helpers
# ═════════════════════════════════════════════════════════════════════════════


async def _http_post(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(f"{base_url}/monitor/action", json=payload)
        resp.raise_for_status()
        return resp.json()


async def _kill_selected(
    base_url: str,
    panel: int,
    index: int,
    snapshot: dict[str, Any] | None,
) -> str:
    """Kill the currently selected job/session. Returns a status message."""
    if snapshot is None:
        return "No data — nothing to kill"

    if panel == PANEL_JOBS:
        jobs = snapshot.get("jobs", [])
        if not jobs or index < 0 or index >= len(jobs):
            return "No job selected"
        req_id = jobs[index].get("request_id", "")
        if not req_id:
            return "No request id for selected job"
        try:
            res = await _http_post(base_url, {"action": "kill_job", "request_id": req_id})
            if res.get("killed"):
                return f"Killed job {req_id}"
            return f"Job {req_id}: not found"
        except Exception as exc:  # noqa: BLE001
            return f"kill_job {req_id}: error — {exc}"

    # Sessions panel — no kill endpoint exists for sessions
    sessions = snapshot.get("sessions", [])
    if not sessions or index < 0 or index >= len(sessions):
        return "No session selected"
    sid = sessions[index].get("session_id", "")
    return f"Session {sid}: cannot kill (no session kill endpoint)"


# ═════════════════════════════════════════════════════════════════════════════
# TUI
# ═════════════════════════════════════════════════════════════════════════════


async def run(url: str, token: str | None = None) -> None:
    """Run the interactive monitor TUI.

    Parameters
    ----------
    url:
        Base URL of the Kali MCP Server, e.g. ``http://127.0.0.1:8399``.
    token:
        Optional bearer token (``MCP_API_TOKEN``) sent with the SSE
        connection. Required when the server has authentication enabled.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    client = SseClient(f"{url}/monitor/stream", headers=headers)
    await client.connect()

    loop = asyncio.get_event_loop()
    input_queue: asyncio.Queue[str] = asyncio.Queue()
    fd = sys.stdin.fileno()

    # Put stdin in cbreak mode: single keypresses available immediately,
    # no Enter required, but signals (Ctrl+C) still work.
    old_settings = None
    try:
        old_settings = termios.tcgetattr(fd)
    except Exception:  # noqa: BLE001
        old_settings = None
    if old_settings is not None:
        try:
            tty.setcbreak(fd)
        except Exception:  # noqa: BLE001
            old_settings = None

    def _read_stdin() -> None:
        """Blocking stdin reader in a background thread."""
        try:
            while True:
                ch = os.read(fd, 1)
                if not ch:
                    break
                try:
                    loop.call_soon_threadsafe(input_queue.put_nowait, ch.decode(errors="replace"))
                except Exception:  # noqa: BLE001
                    break
        except OSError:
            pass

    stdin_thread = threading.Thread(target=_read_stdin, daemon=True)
    stdin_thread.start()

    # ── Selection state ──────────────────────────────────────────────
    panel = PANEL_SESSIONS  # 0 = sessions (left), 1 = jobs (right)
    index = 0  # selected row within active panel
    escape_buf = ""  # buffer for arrow-key escape sequences
    last_k_time = 0.0  # timestamp of last 'k' press (for double-tap)
    DOUBLE_TAP_WINDOW = 0.5  # seconds

    snapshot = client.get_latest_snapshot() or {}
    # Show connection error if the SSE stream is failing
    conn_err = client.last_error
    status_msg = (
        "q: quit · r: refresh · f: force cleanup · k k: kill selected · "
        "←→: switch panel · ↑↓: move selection"
    )
    if conn_err:
        status_msg = f"Connection error: {conn_err} · q: quit · r: retry"
    layout = build_layout(snapshot, status_msg, panel, index)

    # Old-style kill-by-id mode (single k then type ID)
    waiting_for_kill_id = False
    kill_id_buffer = ""

    try:
        with Live(layout, refresh_per_second=4, screen=False) as live:
            while True:
                snapshot_task = asyncio.create_task(client.next_snapshot())
                input_task = asyncio.create_task(input_queue.get())

                done, pending = await asyncio.wait(
                    [snapshot_task, input_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

                result = done.pop().result()

                # ── New snapshot from SSE ──────────────────────────────
                if isinstance(result, dict):
                    snapshot = result
                    # Clear connection error once data flows again
                    conn_err = client.last_error
                    if conn_err:
                        status_msg = (
                            "q: quit · r: refresh · f: force cleanup · k k: kill selected · "
                            "←→: switch panel · ↑↓: move selection"
                        )
                    layout = build_layout(
                        snapshot,
                        status_msg,
                        panel,
                        index,
                    )
                    live.update(layout, refresh=True)
                    continue

                # ── User input (single keypress in cbreak mode) ────────
                key = result

                # Ctrl+C → quit
                if key == "\x03":
                    break

                # ── Escape-sequence buffering (arrow keys etc.) ────────
                if key == "\x1b":
                    escape_buf = key
                    continue
                if escape_buf:
                    escape_buf += key
                    # Only complete 3-char sequences match arrow keys.
                    # Shorter prefixes ("\x1b", "\x1b[") need more input.
                    if len(escape_buf) == 1:
                        # Just "\x1b" — wait for more
                        continue
                    if len(escape_buf) == 2:
                        # "\x1b[" — wait for the final char
                        if escape_buf != "\x1b[":
                            # Not a CSI sequence — reset
                            escape_buf = ""
                        continue
                    # len == 3: check for arrow keys
                    if escape_buf == "\x1b[A":  # Up
                        if panel == PANEL_SESSIONS:
                            items = snapshot.get("sessions", []) if snapshot else []
                        else:
                            items = snapshot.get("jobs", []) if snapshot else []
                        if items:
                            index = (index - 1) % len(items)
                        escape_buf = ""
                        layout = build_layout(snapshot, status_msg, panel, index)
                        live.update(layout, refresh=True)
                        continue
                    elif escape_buf == "\x1b[B":  # Down
                        if panel == PANEL_SESSIONS:
                            items = snapshot.get("sessions", []) if snapshot else []
                        else:
                            items = snapshot.get("jobs", []) if snapshot else []
                        if items:
                            index = (index + 1) % len(items)
                        escape_buf = ""
                        layout = build_layout(snapshot, status_msg, panel, index)
                        live.update(layout, refresh=True)
                        continue
                    elif escape_buf == "\x1b[C":  # Right → switch to jobs panel
                        panel = PANEL_JOBS
                        index = 0
                        jobs = snapshot.get("jobs", []) if snapshot else []
                        if not jobs:
                            index = -1
                        escape_buf = ""
                        status_msg = "Panel: Jobs — k k to kill selected job"
                        layout = build_layout(snapshot, status_msg, panel, index)
                        live.update(layout, refresh=True)
                        continue
                    elif escape_buf == "\x1b[D":  # Left → switch to sessions panel
                        panel = PANEL_SESSIONS
                        index = 0
                        sessions = snapshot.get("sessions", []) if snapshot else []
                        if not sessions:
                            index = -1
                        escape_buf = ""
                        status_msg = "Panel: Sessions — k k has no effect (no kill endpoint)"
                        layout = build_layout(snapshot, status_msg, panel, index)
                        live.update(layout, refresh=True)
                        continue
                    else:
                        # Unknown 3-char escape sequence — reset
                        escape_buf = ""
                        continue

                # ── Old-style kill-by-id mode ──────────────────────────
                if waiting_for_kill_id:
                    # Enter → submit the request id
                    if key in ("\r", "\n"):
                        req_id = kill_id_buffer.strip()
                        if req_id:
                            try:
                                res = await _http_post(
                                    f"{url}/monitor/action",
                                    {"action": "kill_job", "request_id": req_id},
                                )
                                status_msg = (
                                    f"kill_job {req_id}: "
                                    f"{'killed' if res.get('killed') else 'not found'}"
                                )
                            except Exception as exc:  # noqa: BLE001
                                status_msg = f"kill_job {req_id}: error — {exc}"
                        else:
                            status_msg = "kill_job cancelled (no id)"
                        waiting_for_kill_id = False
                        kill_id_buffer = ""
                        layout = build_layout(snapshot, status_msg, panel, index)
                        live.update(layout, refresh=True)
                    # Backspace / delete → remove last char
                    elif key in ("\x7f", "\x08"):
                        kill_id_buffer = kill_id_buffer[:-1]
                        layout = build_layout(
                            snapshot,
                            f"Enter request id to kill: {kill_id_buffer}_",
                            panel,
                            index,
                        )
                        live.update(layout, refresh=True)
                    # Printable char → accumulate
                    elif len(key) == 1 and key.isprintable():
                        kill_id_buffer += key
                        layout = build_layout(
                            snapshot,
                            f"Enter request id to kill: {kill_id_buffer}_",
                            panel,
                            index,
                        )
                        live.update(layout, refresh=True)
                    # Escape → cancel back to normal mode
                    elif key == "\x1b":
                        waiting_for_kill_id = False
                        kill_id_buffer = ""
                        layout = build_layout(
                            snapshot,
                            status_msg,
                            panel,
                            index,
                        )
                        live.update(layout, refresh=True)
                    # 'q' while waiting → quit anyway
                    elif key == "q":
                        break
                    continue

                # ── Normal mode keybindings ────────────────────────────
                if key == "q":
                    break

                elif key == "r":
                    latest = client.get_latest_snapshot() or {}
                    snapshot = latest
                    # Refresh connection error status on manual refresh
                    conn_err = client.last_error
                    if conn_err:
                        status_msg = f"Connection error: {conn_err} · q: quit · r: retry"
                    layout = build_layout(
                        latest,
                        status_msg,
                        panel,
                        index,
                    )
                    live.update(layout, refresh=True)

                elif key == "f":
                    try:
                        res = await _http_post(f"{url}/monitor/action", {"action": "force_cleanup"})
                        status_msg = f"force_cleanup: {res.get('cleaned', 0)} cleaned"
                    except Exception as exc:  # noqa: BLE001
                        status_msg = f"force_cleanup: error — {exc}"
                    layout = build_layout(snapshot, status_msg, panel, index)
                    live.update(layout, refresh=True)

                elif key == "k":
                    now = time.monotonic()
                    if now - last_k_time <= DOUBLE_TAP_WINDOW:
                        # Double-tap → kill the selected item
                        last_k_time = 0.0
                        kill_msg = await _kill_selected(url, panel, index, snapshot)
                        status_msg = kill_msg
                        layout = build_layout(snapshot, status_msg, panel, index)
                        live.update(layout, refresh=True)
                    else:
                        # Single k → start old-style ID entry mode
                        last_k_time = now
                        waiting_for_kill_id = True
                        kill_id_buffer = ""
                        layout = build_layout(
                            snapshot,
                            "Enter request id to kill: ",
                            panel,
                            index,
                        )
                        live.update(layout, refresh=True)

    except (KeyboardInterrupt, EOFError):
        # Ctrl+C or Ctrl+D — exit gracefully without traceback noise
        pass
    finally:
        if old_settings is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:  # noqa: BLE001, S110
                pass
        # Clear the screen on exit so the TUI doesn't leave artifacts
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()
        await client.close()


def main(url: str = "http://127.0.0.1:8399", token: str | None = None) -> None:
    """Entry point for ``python -m kmcp monitor``."""
    asyncio.run(run(url, token))
