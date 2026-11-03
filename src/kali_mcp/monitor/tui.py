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
  * ``f`` — force cleanup all tracked executions (with confirmation)
  * ``k`` — kill a specific job (prompts for request id)
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import httpx
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from kali_mcp.monitor.sse_client import SseClient

# ════════════════════════════════════════════════════════════════════════════
# Cyberspace color palette (dark-background friendly)
# ════════════════════════════════════════════════════════════════════════════

CYBERSPACE_CYAN = "#18FFFF"   # bright electric cyan — headers / primary text
GUMMY_AMBER = "#FFBF00"       # gummy amber — highlights / values / jobs
GUMMY_PINK = "#FF69B4"        # hot pink / magenta — alerts / actions / borders
GUMMY_LIGHT_PINK = "#FFB6C1"  # soft pink — secondary text
DARK_PANEL_BG = "#0a0a0f"     # near-black panel background — deep cyberspace


def _styled_text(content: str, style: str) -> Text:
    return Text(content, style=style)


# ════════════════════════════════════════════════════════════════════════════
# Panel builders
# ════════════════════════════════════════════════════════════════════════════


def _sessions_panel(sessions: list[dict[str, Any]]) -> Panel:
    table = Table(show_header=True, header_style=f"bold {GUMMY_AMBER}", expand=True)
    table.add_column("Session ID", style=CYBERSPACE_CYAN, width=14)
    table.add_column("Connected At", style=GUMMY_LIGHT_PINK, width=20)
    table.add_column("Last Activity", style=GUMMY_LIGHT_PINK, width=20)
    table.add_column("Client", style=CYBERSPACE_CYAN, width=26)

    for s in sessions:
        ci = s.get("client_info", {}) or {}
        client_str = f"{ci.get('name', '-')}/{ci.get('version', '-')}"
        table.add_row(
            str(s.get("session_id", "-")),
            str(s.get("connected_at", "-")),
            str(s.get("last_activity", "-")),
            client_str,
        )

    return Panel(
        table,
        title=_styled_text("Connected Users", f"bold {GUMMY_PINK}"),
        border_style=GUMMY_PINK,
        title_align="left",
    )


def _jobs_panel(jobs: list[dict[str, Any]]) -> Panel:
    table = Table(show_header=True, header_style=f"bold {GUMMY_AMBER}", expand=True)
    table.add_column("Request ID", style=CYBERSPACE_CYAN, width=14)
    table.add_column("Tool", style=CYBERSPACE_CYAN, width=16)
    table.add_column("Elapsed (s)", style=GUMMY_AMBER, width=12, justify="right")

    for j in jobs:
        table.add_row(
            str(j.get("request_id", "-")),
            str(j.get("tool", "-")),
            f"{j.get('elapsed_seconds', 0):.1f}",
        )

    return Panel(
        table,
        title=_styled_text("Running Jobs", f"bold {GUMMY_PINK}"),
        border_style=GUMMY_PINK,
        title_align="left",
    )


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

    layout["middle"].split_row(
        Layout(
            _sessions_panel(snapshot.get("sessions", []) if snapshot else []),
            name="sessions",
        ),
        Layout(_jobs_panel(snapshot.get("jobs", []) if snapshot else []), name="jobs"),
    )
    layout["bottom"].update(
        _health_panel(snapshot.get("health", {}) if snapshot else {})
    )

    return layout


# ════════════════════════════════════════════════════════════════════════════
# HTTP action helpers
# ════════════════════════════════════════════════════════════════════════════


async def _http_post(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.post(f"{base_url}/monitor/action", json=payload)
        resp.raise_for_status()
        return resp.json()


# ════════════════════════════════════════════════════════════════════════════
# TUI
# ════════════════════════════════════════════════════════════════════════════


async def run(url: str) -> None:
    """Run the interactive monitor TUI.

    Parameters
    ----------
    url:
        Base URL of the Kali MCP Server, e.g. ``http://127.0.0.1:8399``.
    """
    client = SseClient(f"{url}/monitor/stream")
    await client.connect()

    loop = asyncio.get_event_loop()
    input_queue: asyncio.Queue[str] = asyncio.Queue()
    _reader_fd = sys.stdin.fileno()

    def _on_stdin_readable() -> None:
        """Callback when stdin has data available (non-blocking)."""
        try:
            line = sys.stdin.readline()
        except Exception:
            line = ""
        if line:
            input_queue.put_nowait(line.strip())

    loop.add_reader(_reader_fd, _on_stdin_readable)

    snapshot = client.get_latest_snapshot() or {}
    layout = build_layout(
        snapshot,
        f"Press q to quit · f: force cleanup · k: kill job",
    )

    waiting_for_kill_id = False

    try:
        with Live(layout, refresh_per_second=4, screen=True) as live:
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
                    layout = build_layout(
                        snapshot,
                        f"Press q to quit · f: force cleanup · k: kill job",
                    )
                    live.update(layout)
                    continue

                # ── User input ─────────────────────────────────────────
                key = result.lower()

                if waiting_for_kill_id:
                    # Expecting a request id
                    req_id = result.strip()
                    if req_id:
                        try:
                            res = await _http_post(
                                f"{url}/monitor/action",
                                {"action": "kill_job", "request_id": req_id},
                            )
                            status_msg = (
                                f"kill_job {req_id}: {'killed' if res.get('killed') else 'not found'}"
                            )
                        except Exception as exc:  # noqa: BLE001
                            status_msg = f"kill_job {req_id}: error — {exc}"
                    else:
                        status_msg = "kill_job cancelled (no id)"
                    waiting_for_kill_id = False
                    layout = build_layout(snapshot, status_msg)
                    live.update(layout)
                    continue

                if key == "q":
                    break

                elif key == "r":
                    # Force an immediate re-render from the latest snapshot
                    latest = client.get_latest_snapshot() or {}
                    layout = build_layout(
                        latest, f"Press q to quit · f: force cleanup · k: kill job"
                    )
                    live.update(layout)

                elif key == "f":
                    try:
                        res = await _http_post(
                            f"{url}/monitor/action", {"action": "force_cleanup"}
                        )
                        status_msg = f"force_cleanup: {res.get('cleaned', 0)} cleaned"
                    except Exception as exc:  # noqa: BLE001
                        status_msg = f"force_cleanup: error — {exc}"
                    layout = build_layout(snapshot, status_msg)
                    live.update(layout)

                elif key == "k":
                    waiting_for_kill_id = True
                    layout = build_layout(
                        snapshot,
                        "Enter request id to kill (or Enter to cancel):",
                    )
                    live.update(layout)

    except (KeyboardInterrupt, EOFError):
        # Ctrl+C or Ctrl+D — exit gracefully without traceback noise
        pass
    finally:
        loop.remove_reader(_reader_fd)
        await client.close()


def main(url: str = "http://127.0.0.1:8399") -> None:
    """Entry point for ``python -m kali_mcp monitor``."""
    asyncio.run(run(url))
