# Kali MCP Server — Interactive Monitor Implementation Plan

**Based on:** Existing server architecture (`src/kali_mcp/server.py`, `src/kali_mcp/execution.py`)
**Status:** Ready for implementation  
**Scope:** Plan only (no code in this session)  
**Decisions captured from requirements session:**

| Decision | Value |
|---|---|
| Connected users | MCP client sessions (tracked via session IDs) |
| Jobs to monitor | Active tool executions (subprocess commands via ExecutionEngine) |
| Interface | CLI/TUI (text-based live monitor) |
| Live updates | Push (SSE/WebSocket) |
| State persistence | In-memory (resets on restart) |
| Monitor actions | Read + act (kill jobs, force cleanup) |
| Alerting | None yet (status display only) |

---

## 1. Overview

Add a live, interactive monitoring subsystem to the Kali MCP Server that lets an operator see:

- **Connected users** — active MCP client sessions with session IDs, connect time, and last activity
- **Running jobs** — active subprocess executions (nmap, sqlmap, etc.) with tool name, command, elapsed time, and progress
- **Server health** — uptime, memory, active execution count, registered tool count, stuck executions

The monitor is a **CLI/TUI** that connects to the running server over **SSE/WebSocket** for push-based live updates. State lives **in-memory** (shared with the server process). The TUI supports **read + act** actions: kill a stuck job, trigger `force_cleanup`, and view health.

No alerting is included in this phase.

---

## 2. Design Principles

1. **In-process state** — The monitor reads the same in-memory objects the server already maintains (`ExecutionEngine`, `HealthMonitor`, session registry). No new persistence layer.
2. **Push, not poll** — The server pushes status deltas to connected TUI clients over SSE so the display stays alive without refresh.
3. **Reuse existing primitives** — Leverage `engine.get_stats()`, `engine.get_stuck_executions()`, `health.get_status()`, and the existing FastMCP session infrastructure rather than building duplicate trackers.
4. **Non-blocking** — Monitoring never slows down tool execution. All reads are snapshots; all actions are fire-and-forget with confirmation.
5. **Graceful degradation** — If the TUI disconnects, the server continues unaffected. If the server restarts, in-memory state is lost (by design).

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    TUI Client (CLI)                         │
│  (rich/textual) — connects via SSE, shows live status       │
│  Send actions: kill job, force cleanup, view health         │
└──────────────────┬──────────────────────────────────────────┘
                   │ SSE (push) + HTTP POST (actions)
┌──────────────────▼──────────────────────────────────────────┐
│              Kali MCP Server (:8399)                        │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────┐  │
│  │ Session Registry│  │ ExecutionEngine  │  │ Health    │  │
│  │ (new)           │  │ (existing)       │  │ Monitor   │  │
│  │ - session_id    │  │ - active jobs    │  │ (existing)│  │
│  │ - connected_at  │  │ - command        │  │ - uptime  │  │
│  │ - last_activity │  │ - elapsed        │  │ - memory  │  │
│  └─────────────────┘  └──────────────────┘  └───────────┘  │
│           │              │               │                  │
│           └──────────────┴───────────────┴─────────────────┘
│                    Monitor Module (new)                     │
│  - Aggregates session + job + health snapshots              │
│  - SSE broadcast loop                                       │
│  - Action handlers (kill job, force cleanup)                │
└─────────────────────────────────────────────────────────────┘
```

### Components

**A. Session Registry** (`src/kali_mcp/monitor/sessions.py` — new)
- Tracks active MCP client sessions.
- On session connect: record `session_id`, `connect_at`, `client_info` (from MCP `initialize` params), `last_activity`.
- On session disconnect / `initialized` notification: update `last_activity`; remove on session end.
- Provides `list_sessions()` → list of session dicts.

**B. Job View** (reuse `src/kali_mcp/execution.py`)
- `ExecutionEngine` already tracks `_active` (request_id → tool) and `_request_times` (request_id → start monotonic).
- Expose `engine.get_active_jobs()` → list of `{request_id, tool, elapsed_seconds, command}`.
- Reuse `engine.get_stuck_executions()` for stuck detection.

**C. Monitor Module** (`src/kali_mcp/monitor/__init__.py` — new)
- Aggregates: sessions + active jobs + health status into a single snapshot.
- Maintains a set of SSE client connections for push broadcast.
- On any state change (session connect/disconnect, job start/end), broadcast snapshot to all SSE clients.
- Action handlers:
  - `kill_job(request_id)` → calls engine cleanup for that request
  - `force_cleanup()` → calls `engine.force_cleanup()`
  - `get_health()` → calls `health.get_status()`

**D. SSE Endpoint** (in `src/kali_mcp/server.py`)
- New route `GET /monitor/stream` → SSE stream emitting JSON snapshots every N seconds and on state change.
- New route `POST /monitor/action` → JSON body `{action, payload}` → execute action, return result.

**E. CLI/TUI** (new standalone script or `python -m kali_mcp monitor`)
- Built with `rich` (already a transitive dep) or `textual` if available; fallback to plain `curses`-free loop.
- Connects to `http://host:port/monitor/stream` via SSE.
- Renders three panels: Connected Users, Running Jobs, Server Health.
- Keybindings: `k` kill job, `f` force cleanup, `r` refresh health, `q` quit.
- Action confirmation prompt before destructive actions.

---

## 4. File Changes

### New files
| File | Purpose |
|---|---|
| `src/kali_mcp/monitor/__init__.py` | Monitor module: snapshot aggregation, SSE broadcast, action handlers |
| `src/kali_mcp/monitor/sessions.py` | MCP session registry (connect/disconnect tracking) |
| `src/kali_mcp/monitor/tui.py` | CLI/TUI client (rich-based live display) |
| `src/kali_mcp/monitor/sse_client.py` | SSE client for the TUI to consume push stream |
| `tests/unit/test_monitor_sessions.py` | Unit tests for session registry |
| `tests/unit/test_monitor_snapshot.py` | Unit tests for snapshot aggregation |
| `tests/unit/test_monitor_actions.py` | Unit tests for kill_job / force_cleanup handlers |

### Modified files
| File | Change |
|---|---|
| `src/kali_mcp/server.py` | Register `GET /monitor/stream` and `POST /monitor/action` routes; import monitor module; hook session connect/disconnect into session registry |
| `src/kali_mcp/execution.py` | Add `get_active_jobs()` method (thin wrapper over existing `_active`/`_request_times`) |
| `pyproject.toml` | Add `rich` or `textual` as optional TUI dependency; add `monitor` console script entry point |
| `Justfile` | Add `just monitor` command to launch the TUI |

---

## 5. Detailed Design

### 5.1 Session Registry

```python
# src/kali_mcp/monitor/sessions.py

class SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, dict] = {}  # session_id -> {connect_at, last_activity, client_info}
        self._lock = threading.RLock()

    def on_connect(self, session_id: str, client_info: dict) -> None:
        with self._lock:
            self._sessions[session_id] = {
                "session_id": session_id,
                "connected_at": utc_now_iso(),
                "last_activity": utc_now_iso(),
                "client_info": client_info or {},
            }

    def on_activity(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id]["last_activity"] = utc_now_iso()

    def on_disconnect(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[dict]:
        with self._lock:
            return list(self._sessions.values())
```

Session lifecycle hooks:
- In `server.py`, the FastMCP `Context` session is available via `ctx.session`. Hook into the request handler wrapper to call `registry.on_connect(session_id, ...)` on first tool invocation and `on_disconnect` when the session closes.
- Alternative: FastMCP lifespan/session middleware. If FastMCP doesn't expose a clean session connect/disconnect hook, approximate by tracking `ctx.session` identity on each tool call and treating absence as disconnect.

### 5.2 Job View

Add to `ExecutionEngine`:

```python
def get_active_jobs(self) -> list[dict]:
    now = time.monotonic()
    with self._lock:
        return [
            {
                "request_id": rid,
                "tool": tool,
                "elapsed_seconds": round(now - self._request_times.get(rid, now), 1),
            }
            for rid, tool in self._active.items()
        ]
```

### 5.3 Snapshot

```python
# monitor/__init__.py

def build_snapshot(session_registry, engine, health) -> dict:
    return {
        "timestamp": utc_now_iso(),
        "sessions": session_registry.list_sessions(),
        "jobs": engine.get_active_jobs(),
        "health": health.get_status(),
    }
```

### 5.4 SSE Broadcast

The monitor module keeps a set of `asyncio.Queue` objects (one per SSE client). On any relevant state change (session connect/disconnect, job start/end, health tick), it pushes the new snapshot to all queues.

The SSE endpoint (`GET /monitor/stream`) yields `data: {json}\n\n` for each item from its queue.

### 5.5 Action Endpoint

`POST /monitor/action` accepts JSON:
```json
{"action": "kill_job", "request_id": "abc123"}
{"action": "force_cleanup"}
{"action": "get_health"}
```

Returns JSON result. Destructive actions (`kill_job`, `force_cleanup`) require no additional auth beyond the existing `MCP_API_TOKEN` middleware (already applied to all HTTP routes).

### 5.6 TUI

- Single-file `rich`-based app.
- Three panels (Live, Layout from `rich`):
  1. **Connected Users** — table: session_id, connected_at, last_activity, client_info
  2. **Running Jobs** — table: request_id, tool, elapsed_seconds
  3. **Server Health** — panel: uptime, active_executions, total_requests, total_errors, memory_mb, tools_registered
- SSE client reads stream and triggers `snapshot_received` event → re-render.
- Keybindings:
  - `k` → prompt for request_id → `kill_job`
  - `f` → confirm → `force_cleanup`
  - `r` → request fresh snapshot
  - `q` → quit
- If `rich` is unavailable, fall back to a simple `print`-based loop that re-renders every 2 seconds.

---

## 6. Implementation Phases

### Phase 1 — Session Registry + Job View (Foundation)
1. Create `src/kali_mcp/monitor/__init__.py`, `sessions.py`
2. Add `ExecutionEngine.get_active_jobs()`
3. Wire session connect/disconnect hooks in `server.py`
4. Unit tests for session registry and snapshot
**Exit criteria:** `python -c "from kali_mcp.monitor import build_snapshot"` works; session connect/disconnect tracked.

### Phase 2 — SSE Endpoint + Action Handlers
1. Add `GET /monitor/stream` and `POST /monitor/action` to `server.py`
2. Implement SSE broadcast from monitor module
3. Implement kill_job / force_cleanup handlers
4. Unit tests for actions
**Exit criteria:** `curl -N http://localhost:8399/monitor/stream` emits JSON snapshots; `POST /monitor/action` kills a job / forces cleanup.

### Phase 3 — CLI/TUI
1. Create `src/kali_mcp/monitor/tui.py` and `sse_client.py`
2. Add `monitor` console script to `pyproject.toml`
3. Add `just monitor` command
4. Manual smoke test: launch server, launch TUI, run a tool, watch job appear/disappear
**Exit criteria:** `python -m kali_mcp monitor` connects and displays live sessions/jobs/health.

### Phase 4 — Hardening (optional, future)
- Reconnection with backoff for the TUI SSE client
- Snapshot history / last-N statuses
- Alerting thresholds (stuck job > X seconds)

---

## 7. Testing Strategy

| Layer | What | Where |
|---|---|---|
| Unit | Session registry connect/disconnect/list | `tests/unit/test_monitor_sessions.py` |
| Unit | Snapshot aggregation shape | `tests/unit/test_monitor_snapshot.py` |
| Unit | kill_job / force_cleanup handlers | `tests/unit/test_monitor_actions.py` |
| Integration | SSE stream emits snapshots | `tests/integration/test_monitor_sse.py` |
| Integration | Action endpoint kills job | `tests/integration/test_monitor_actions.py` |
| Manual | TUI connects and shows live data | `just monitor` smoke test |

---

## 8. Deliverables

1. `docs/interactive-monitor-plan.md` — this document
2. `src/kali_mcp/monitor/__init__.py`
3. `src/kali_mcp/monitor/sessions.py`
4. `src/kali_mcp/monitor/tui.py`
5. `src/kali_mcp/monitor/sse_client.py`
6. Modified `src/kali_mcp/server.py` (routes + session hooks)
7. Modified `src/kali_mcp/execution.py` (`get_active_jobs`)
8. Modified `pyproject.toml` (deps + console script)
9. Modified `Justfile` (`just monitor`)
10. 3+ new test files under `tests/unit/` and `tests/integration/`

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| FastMCP doesn't expose session connect/disconnect hooks cleanly | Approximate via tool-call context: track `ctx.session` on each request; treat a session not seen in N seconds as disconnected |
| SSE broadcast blocks tool execution | Use `asyncio.Queue` per client with `put_nowait`; full queues drop oldest snapshot (non-blocking) |
| TUI crashes on malformed snapshot | Wrap snapshot parsing in try/except; display error line, keep running |
| In-memory state lost on restart | Documented behavior; acceptable per requirements |
| Kill job affects the server process itself | Jobs run in `start_new_session` subprocesses; killing the process group cannot hit the server (already handled by `utils/process.kill_process_tree`) |

---

**Next step:** Approve this plan, and I'll implement Phase 1 (session registry + job view + unit tests).