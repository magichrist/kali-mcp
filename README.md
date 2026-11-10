<h1 align="center">✦ kali-mcp ✦</h1>

<p align="center"><em>A warm, expressive MCP server that puts 56 Kali Linux pentesting tools at your AI agent's fingertips — soft voltage around sharp security tooling.</em></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/magichrist/kali-mcp?color=c58af2" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10+-89b4fa" alt="Python 3.10+"></a>
  <a href="https://pypi.org/project/kmcp/"><img src="https://img.shields.io/badge/pypi-kmcp-a6d189" alt="kmcp on PyPI"></a>
</p>

> ⚠️ **Security warning:** This server executes real offensive security tooling. Expose it only on a **trusted local network** and never on the public internet or in untrusted environments. Anyone who can reach the endpoint can run Kali tools against targets you may not own. Always set `MCP_API_TOKEN` when exposing beyond localhost, and ensure you have explicit authorization for every target you scan.

The Kali MCP Server is a production-grade Model Context Protocol (MCP) server that exposes Kali Linux penetration-testing tools (nmap, sqlmap, nuclei, hydra, metasploit, and 50 more) to AI agents. Every tool call is validated, every execution is sandboxed with timeouts, and every result can be shared between agents through a built-in inter-agent vault.

## $\textsf{\color{#89b4fa}{✧}}$ At a glance

| | |
|---|---|
| **Transport** | HTTP — `sse` (default, `:8399/sse`) or `streamable-http` (`:8399/mcp`), Bearer-token auth |
| **Tools** | 56 native Kali wrappers + `generic_command` escape hatch |
| **Persistence** | SQLite (targets, scans, findings, credentials) + inter-agent vault |
| **Orchestration** | Playbooks (recon / webapp / AD / custom engine) with `{{target}}` substitution and resume |
| **Parallelism** | `parallel_execute` with deduplicated aggregate results |
| **Monitoring** | Live CLI/TUI with SSE push, job kill, force cleanup |
| **Safety** | 3-layer timeout defense, process-tree cleanup, semaphore limits, output truncation |

## $\textsf{\color{#fab387}{♡}}$ Get started

### Requirements

- Python 3.10+
- A host with the Kali tools you want to run installed (the server wraps binaries; it doesn't install them)
- `pip`

### Install

```bash
pip install kmcp
```

### Quickstart

Three commands and you're live:

```bash
kmcp init    # 1. generate .env from .env.example with a secure MCP_API_TOKEN
kmcp start   # 2. start the server (alias: kmcp s)
             # 3. open http://localhost:8399/studio in your browser
```

**Step 1 — `kmcp init`.** Creates a `.env` at the repo root from `.env.example`, filling `MCP_API_TOKEN` with a cryptographically secure random value. If a `.env` already exists, it backfills only missing or empty required keys — your hand-set values are never overwritten. (`--force` regenerates from scratch, backing up the old file to `.env.bak`.)

> 💡 Keep the generated `MCP_API_TOKEN` handy — it lives in `.env`, and everything that calls the server (Studio UI, MCP clients, the monitor TUI) authenticates with it. See [Authentication](#authentication) below.

**Step 2 — `kmcp start`.** Boots the server, binding to `MCP_HOST`/`MCP_PORT` from `.env` (`0.0.0.0:8399` by default after `kmcp init`). With custom host/port:

```bash
kmcp start --host 127.0.0.1 --port 9000
```

**Step 3 — open the Studio.** Browse to `http://localhost:8399/studio` in your browser. The UI loads from `/studio`, and the Studio API behind it is protected by the `MCP_API_TOKEN` that `kmcp init` put in your `.env`. On the first API call the UI shows a one-time *"API token required"* prompt: open `.env`, copy the `MCP_API_TOKEN` value, paste it, and hit **Save & retry**. The token is stored only in your browser (`localStorage`, key `kmcp_token`) and sent as a `Bearer` header on every request from then on. To clear it, use the **Clear stored token** button in the Studio's server/info panel.

> ⚠️ **The server refuses to start without a token.** If `MCP_API_TOKEN` is empty (or missing), startup fails with an error. That's by design — run `kmcp init` to generate one. Local dev only, you can bypass with `KALI_MCP_INSECURE=1`.

Prefer one command? `kmcp studio` (alias `st`) opens the Studio in a browser — auto-starting the server first if it isn't running — and prints the Studio URL (it maps a wildcard bind like `0.0.0.0` to your machine's LAN IP so the link works from other machines too).

```bash
kmcp studio          # open the Studio UI in your browser
kmcp studio --no-browser   # just print the URL
```

### Connecting MCP clients

Point any MCP client at the server's HTTP endpoint. Which path depends on `MCP_TRANSPORT` in `.env`:

| `MCP_TRANSPORT` | Endpoint URL |
|---|---|
| `sse` *(default)* | `http://localhost:8399/sse` |
| `streamable-http` | `http://localhost:8399/mcp` |

Authenticate with the token from `.env`:

```
Authorization: Bearer <MCP_API_TOKEN>
```

Clients that can't set headers can pass the token as a query parameter instead — set `KALI_MCP_TOKEN_IN_QUERY=true` in `.env` and append `?token=<MCP_API_TOKEN>`.

### Authentication

| Surface | How to authenticate |
|---|---|
| Studio UI (`/studio`) | Paste the `MCP_API_TOKEN` from `.env` once at the prompt; stored in the browser as `kmcp_token` |
| Studio REST API (`/api/*`) | `Authorization: Bearer <MCP_API_TOKEN>` |
| MCP endpoint (`/mcp`, `/sse`) | `Authorization: Bearer <MCP_API_TOKEN>` (or `?token=` with `KALI_MCP_TOKEN_IN_QUERY`) |
| Monitor TUI (`kmcp monitor`) | Reads `MCP_API_TOKEN` from `.env` automatically |

To run the server without any auth (local testing only), set `KALI_MCP_INSECURE=1` in `.env` — an empty `MCP_API_TOKEN` alone will refuse to start.

### Debug mode

```bash
MCP_DEBUG=true kmcp start
```

### Configuration

The server reads configuration from `.env` (created by `kmcp init` from `.env.example`). Full variable reference below in [Configuration](#-configuration).

## $\textsf{\color{#c58af2}{✧}}$ `kmcp` CLI reference

All commands also work via their short aliases: `s` (start), `m` (monitor), `p` (purge), `st` (studio).

```bash
# Server lifecycle
kmcp init [--force]          # generate .env from .env.example, with a secure MCP_API_TOKEN
kmcp start [--host H] [--port P]   # start the MCP server (alias: s)
kmcp monitor [URL]           # launch the live monitor TUI (alias: m)
kmcp purge db|vault|all [--confirm/-y]   # wipe stored data (aliases: p)

# Studio
kmcp studio [--no-browser] [--host H] [--port P]   # open the Studio UI (starts the server if needed)

# Playbook management
kmcp playbook list [--status STATUS]
kmcp playbook create --id ID --name NAME [--description D] [--category C] [--author A]
kmcp playbook show ID
kmcp playbook validate ID [--definition FILE] [--for-publish]
kmcp playbook preview ID [--definition FILE]     # dry-run (no execution)
kmcp playbook test ID [--definition FILE]        # controlled test run (mocked tools)
kmcp playbook publish ID --version V [--definition FILE] [--notes N]
kmcp playbook versions ID
kmcp playbook rollback ID --version-id VID
kmcp playbook export ID [--out FILE]
kmcp playbook import FILE [--no-require-approval]
kmcp playbook seed                               # seed built-in YAML playbooks

# Tool registry
kmcp tool list [--provider P] [--visibility V] [--enabled E]
kmcp tool visibility ID agent_callable|playbook_selectable|internal|hidden

# Executions
kmcp execution list [--status S] [--playbook-id ID] [--limit N] [--offset N]
kmcp execution cancel ID
```

`--definition` accepts either a JSON string or a path to a JSON file.

## $\textsf{\color{#c58af2}{✦}}$ Features

**56 Kali tools, natively wrapped.** Nmap, sqlmap, nuclei, ffuf, katana, subfinder, amass, hydra, metasploit, bettercap, responder, zap, wpscan, and more. Each tool validates its arguments against a JSON schema, builds a safe subprocess argument list (no shell injection for native tools), and returns structured JSON with stdout, stderr, exit code, and timing.

**`generic_command`** — the escape hatch. Run any shell command or pipeline not covered by a native wrapper. Full bash scripting supported (pipes, redirects, here-docs).

**`python_command`** — execute Python scripts directly on the host. Full access to installed libraries (scapy, impacket, requests, etc.).

**Playbooks** — multi-step pipelines with `{{target}}` substitution and resume support:

- `playbook_recon` — subfinder → httpx → masscan → whatweb+nmap → nuclei
- `playbook_webapp` — katana → arjun+ffuf → nuclei → sqlmap+commix
- `playbook_ad` — enum4linux → bloodhound → netexec+crackmapexec
- `playbook_engine` — run a custom playbook definition

**`parallel_execute`** — fan out to multiple tools concurrently, then aggregate and deduplicate open ports, vulnerabilities, and credentials.

**Playbook Studio** — a built-in operator web UI (served at `/studio` or a dedicated `STUDIO_PORT`) for authoring, validating, publishing, and running multi-step playbooks on top of the DAG engine:

- Author in the DSL editor or the visual graph builder (drag nodes, wire `depends_on` edges port-to-port, zoom, per-step inspector), then round-trip between the two views losslessly.
- Draft → validate → publish an immutable version; run published versions with declared required inputs; watch execution progress per step (`GET /api/executions/{id}`), cancel, resume, roll back, import/export.
- Govern what agents can see: agent profiles with deny-by-default tool grants (`agent_tool_permissions`) and playbook assignments (`agent_playbook_assignments`). Requests resolve the profile from the `X-Agent-Profile` header, or bind every request to one profile with `MCP_AGENT_PROFILE_ID`. Ungranted tools and unassigned playbooks return a `403`-equivalent forbidden payload; with no profile context the default surface is unchanged.
- Full REST surface at `/api/playbooks`, `/api/executions`, `/api/agents`, `/api/tools`, plus `/api/overview`, `/api/scope`, and `/api/server` for health at a glance.

**Inter-agent vault** — SQLite-backed knowledge store (`artifacts/vault/vault.sqlite` + JSON mirrors). Any agent can write findings, credentials, or notes; any other agent can query them back by category, target, tool, or free-text search. Every tool run is automatically deposited.

**Live monitor TUI** — `kmcp monitor` launches a pastel cyber dashboard showing connected users, running jobs, and server health with SSE push updates. Kill stuck jobs or force cleanup from the dashboard. Press `q` to quit; the screen clears on exit.

**MCP resources & prompts** — `kali://config`, `kali://tools`, `kali://health`, `kali://vault/index`, plus guided workflow prompts (recon, webapp, AD, OSINT, quick scan, report).

## $\textsf{\color{#89b4fa}{⟡}}$ How it works

Every tool call follows the same path:

1. **Validate** — arguments checked against the tool's JSON schema (required fields, IP/CIDR/domain/URL/timeout formats, enums).
2. **Build command** — arguments converted to a safe subprocess argument list. No shell interpolation for native tools; `generic_command` is the only shell path.
3. **Execute** — subprocess runs in its own process group with a 3-layer timeout defense:

   - `asyncio.wait_for` enforced timeout
   - Watchdog thread kills stuck executions
   - Semaphore limits concurrent executions (`MCP_MAX_CONCURRENT`, default 10)

4. **Persist** — run recorded to SQLite (`targets`, `scans`, `findings`, `credentials`) and deposited to the vault.
5. **Respond** — structured JSON with stdout, stderr, exit_code, timing, and success flag.

**Session tracking** — the monitor tracks connected MCP client sessions (connect time, last activity, client info) so you can see who's using the server.

## $\textsf{\color{#fab387}{☾}}$ Configuration

Configuration is loaded from environment variables via `.env`. All values have safe defaults.

| Variable | Default | Description |
|---|---|---|
| `MCP_HOST` | `0.0.0.0` | Listen address |
| `MCP_PORT` | `8399` | Listen port |
| `MCP_SERVER_NAME` | `kali-mcp` | Server name advertised to MCP clients |
| `MCP_SERVER_VERSION` | `1.0.0` | Server version |
| `MCP_API_TOKEN` | *(empty)* | Bearer token; when set, all HTTP routes require `Authorization: Bearer <token>`. **Required** — the server exits at startup if empty unless `KALI_MCP_INSECURE=1` |
| `KALI_MCP_INSECURE` | `false` | Run without authentication (dev only; overrides the token requirement) |
| `KALI_MCP_TOKEN_IN_QUERY` | `false` | Also accept the API token as a `?token=` query parameter |
| `MCP_TRANSPORT` | `sse` | `sse` (`/sse` endpoint) or `streamable-http` (`/mcp` endpoint) |
| `MCP_DEFAULT_TIMEOUT` | `300` | Default command timeout (seconds) |
| `MCP_MAX_TIMEOUT` | `3600` | Hard cap on tool timeout |
| `MCP_MAX_CONCURRENT` | `10` | Semaphore limit for concurrent executions |
| `MCP_LOG_DIR` | `logs` | Structured log directory |
| `MCP_ARTIFACT_DIR` | `artifacts` | Artifact and vault directory |
| `MCP_DEBUG` | `false` | Verbose debug logging |
| `MCP_ENCODING` | `utf-8` | Default text encoding |
| `MCP_RATE_LIMIT` | `0` | Rate limit per minute (0 = unlimited) |
| `MCP_VAULT_MAX_ROW_BYTES` | `26214400` | Max vault row size (25 MB; 0 = unlimited) |
| `MCP_DB_PATH` | `data/kali-mcp.sqlite` | SQLite database path |
| `MCP_DB_ENABLED` | `true` | Write executions to SQLite |
| `MCP_AGENT_PROFILE_ID` | *(empty)* | Bind every MCP request to this agent profile (deny-by-default permissions; unknown id fails closed) |
| `STUDIO_ENABLED` | `true` | Serve the Playbook Studio web UI and REST API |
| `STUDIO_PORT` | `0` | Dedicated Studio port (0 = shared with the MCP server) |
| `STUDIO_DEFAULT_VISIBILITY` | `agent_callable` | Default visibility mode for newly synced tools |

## $\textsf{\color{#c58af2}{◈}}$ Architecture

```
MCP Client (AI agent)
        │ HTTP/SSE
        ▼
┌─────────────────────────────────────────┐
│         Kali MCP Server (:8399)         │
│                                         │
│  ┌─────────────┐  ┌─────────────────┐   │
│  │ Token auth  │  │ CORS Middleware │   │
│  │ (required)  │  │                 │   │
│  └─────────────┘  └─────────────────┘   │
│         │              │                │
│         ▼              ▼                │
│   FastMCP tool dispatch layer           │
│         │              │                │
│   ┌─────────────────────────────┐       │
│   │  Tool registry (56 tools)   │       │
│   └─────────────────────────────┘       │
│         │              │                │
│   ┌─────────────────────────────┐       │
│   │     Execution engine        │       │
│   │  (3-layer timeout, semaphore, │   │
│   │   process-tree cleanup)     │       │
│   └─────────────────────────────┘       │
│         │              │                │
│   ┌─────────────────────────────┐       │
│   │   SQLite DB + Vault store   │       │
│   └─────────────────────────────┘       │
│         │              │                │
│   ┌─────────────────────────────┐       │
│   │   Monitor SSE stream        │       │
│   └─────────────────────────────┘       │
└─────────────────────────────────────────┘
        │              │
        ▼              ▼
  Kali Linux      Monitor TUI
  subprocesses    (kmcp monitor)
```

**Package layout (`src/kali_mcp/`):**

- `server.py` — MCP server, tool dispatch, health monitor, REST routes
- `execution.py` — hardened execution engine (timeout, watchdog, semaphore)
- `security.py` — allowlist, input validation, shell-injection prevention
- `config.py` — env-based configuration
- `models.py` — `ExecutionResult`, `ToolError` dataclasses
- `responses.py` — standardized MCP response builders
- `registry.py` — tool registration and lookup
- `logging_utils.py` — structured JSON logging
- `notifications.py` — MCP server→client notification helpers
- `prompts.py` — MCP prompt templates
- `resources.py` — MCP resources (`kali://*`)
- `db/manager.py` — SQLite persistence
- `utils/process.py` — process tree cleanup
- `utils/vault.py` — SQLite-backed inter-agent vault
- `tools/` — 56 tool wrappers + base class + parsers + playbooks

## $\textsf{\color{#a6d189}{🧪}}$ Tests & checks

```bash
# Full suite (unit + integration + e2e)
just test

# Fast unit tests only
just test-unit

# Integration tests (async engine + tool execution)
just test-integration

# End-to-end (spawns a real server, speaks MCP over HTTP)
just test-e2e
```

The suite runs on `pytest` with `pytest-asyncio`. 803 tests pass, 11 skipped (conditional/environment-dependent). Coverage is approximately 84% across the package.

Quality checks:

- `ruff` — linting (line-length 100)

## $\textsf{\color{#f38ba8}{⚠}}$ Known limitations

- **Kali tools must be installed on the host.** The server wraps binaries like `nmap`, `sqlmap`, `hydra`; it does not install them. If a binary isn't in `PATH`, the tool returns a structured "Binary not found" error with an install hint.
- **`generic_command` runs arbitrary shell.** It's the escape hatch — use it deliberately. It is subject to the same timeout and semaphore limits as native tools.
- **In-memory monitor state.** The live monitor (sessions, active jobs) lives in memory and resets on server restart. Persisted data (SQLite, vault) survives restarts.
- **No alerting yet.** The monitor displays status but does not send alerts for stuck executions or high error rates.
- **Output truncation.** stdout/stderr are capped at 100 KB per stream to prevent memory exhaustion.

## $\textsf{\color{#fab387}{◈}}$ Troubleshooting

| Symptom | Likely cause | Next step |
|---|---|---|
| Server exits at startup: "MCP_API_TOKEN is required" | No token configured | Run `kmcp init` to generate `.env` with a token, or set `MCP_API_TOKEN` yourself (or `KALI_MCP_INSECURE=1` for dev) |
| Server won't start | Port 8399 in use | Set `MCP_PORT` to a free port |
| Tool returns "Binary not found" | Kali tool not installed or not in `PATH` | Install the tool or add it to `PATH` |
| `401 Unauthorized` | `MCP_API_TOKEN` set but no/invalid token | Provide `Authorization: Bearer <token>` or `?token=` query param (with `KALI_MCP_TOKEN_IN_QUERY=true`); in the Studio UI, paste the token from `.env` at the prompt |
| Monitor TUI shows no jobs | No executions currently running | Run a tool first; jobs appear while active |
| `q` doesn't quit TUI | Terminal rendering glitch | Press `q` again; if stuck, `Ctrl+C` |

## License

MIT

---

*Built with soft voltage — sharp security tooling wrapped in a warm, expressive MCP server.*
