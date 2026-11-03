# ✦ kali-mcp

*A warm, expressive MCP server that puts 56 Kali Linux pentesting tools at your AI agent's fingertips — soft voltage around sharp security tooling.*

The Kali MCP Server is a production-grade Model Context Protocol (MCP) server that exposes Kali Linux penetration-testing tools (nmap, sqlmap, nuclei, hydra, metasploit, and 50 more) to AI agents. Every tool call is validated, every execution is sandboxed with timeouts, and every result can be shared between agents through a built-in inter-agent vault.

## ✧ At a glance

| | |
|---|---|
| **Transport** | HTTP/SSE or streamable-http on `:8399/mcp` |
| **Tools** | 56 native Kali wrappers + `generic_command` escape hatch |
| **Persistence** | SQLite (targets, scans, findings, credentials) + inter-agent vault |
| **Orchestration** | Playbooks (recon / webapp / AD / custom engine) with `{{target}}` substitution and resume |
| **Parallelism** | `parallel_execute` with deduplicated aggregate results |
| **Monitoring** | Live CLI/TUI with SSE push, job kill, force cleanup |
| **Safety** | 3-layer timeout defense, process-tree cleanup, semaphore limits, output truncation |

## ♡ Get started

### Requirements

- Python 3.10+
- A host with the Kali tools you want to run installed (the server wraps binaries; it doesn't install them)
- `pip`

### Install

```bash
pip install kmcp
```

### Start the server

Use the `kmcp` CLI:

```bash
kmcp start

# With custom host/port
kmcp start --host 127.0.0.1 --port 9000

# Aliases: s, monitor (m), purge (p)
kmcp s
```

The server listens on `http://0.0.0.0:8399/mcp` by default. Point your MCP client at that URL.

### Debug mode

```bash
MCP_DEBUG=true kmcp start
```

### Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Default | What it does |
|---|---|---|
| `MCP_HOST` | `0.0.0.0` | Listen address |
| `MCP_PORT` | `8399` | Listen port |
| `MCP_TRANSPORT` | `sse` | `sse` or `streamable-http` |
| `MCP_API_TOKEN` | *(empty)* | Bearer token for HTTP auth |
| `MCP_DEFAULT_TIMEOUT` | `300` | Default command timeout (seconds) |
| `MCP_MAX_TIMEOUT` | `3600` | Maximum allowed timeout |
| `MCP_MAX_CONCURRENT` | `10` | Max concurrent tool executions |
| `MCP_DB_ENABLED` | `true` | Write executions to SQLite |
| `MCP_DEBUG` | `false` | Verbose structured logging |

## ✦ Features

**56 Kali tools, natively wrapped.** Nmap, sqlmap, nuclei, ffuf, katana, subfinder, amass, hydra, metasploit, bettercap, responder, zap, wpscan, and more. Each tool validates its arguments against a JSON schema, builds a safe subprocess argument list (no shell injection for native tools), and returns structured JSON with stdout, stderr, exit code, and timing.

**`generic_command`** — the escape hatch. Run any shell command or pipeline not covered by a native wrapper. Full bash scripting supported (pipes, redirects, here-docs).

**`python_command`** — execute Python scripts directly on the host. Full access to installed libraries (scapy, impacket, requests, etc.).

**Playbooks** — multi-step pipelines with `{{target}}` substitution and resume support:
- `playbook_recon` — subfinder → httpx → masscan → whatweb+nmap → nuclei
- `playbook_webapp` — katana → arjun+ffuf → nuclei → sqlmap+commix
- `playbook_ad` — enum4linux → bloodhound → netexec+crackmapexec
- `playbook_engine` — run a custom playbook definition

**`parallel_execute`** — fan out to multiple tools concurrently, then aggregate and deduplicate open ports, vulnerabilities, and credentials.

**Inter-agent vault** — SQLite-backed knowledge store (`artifacts/vault/vault.sqlite` + JSON mirrors). Any agent can write findings, credentials, or notes; any other agent can query them back by category, target, tool, or free-text search. Every tool run is automatically deposited.

**Live monitor TUI** — `kmcp monitor` launches a pastel cyber dashboard showing connected users, running jobs, and server health with SSE push updates. Kill stuck jobs or force cleanup from the dashboard. Press `q` to quit; the screen clears on exit.

**MCP resources & prompts** — `kali://config`, `kali://tools`, `kali://health`, `kali://vault/index`, plus guided workflow prompts (recon, webapp, AD, OSINT, quick scan, report).

## ⟡ How it works

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

## ☾ Configuration

Configuration is loaded from environment variables via `.env`. All values have safe defaults.

| Variable | Default | Description |
|---|---|---|
| `MCP_HOST` | `0.0.0.0` | Listen address |
| `MCP_PORT` | `8399` | Listen port |
| `MCP_SERVER_NAME` | `kali-mcp` | Server name advertised to MCP clients |
| `MCP_SERVER_VERSION` | `1.0.0` | Server version |
| `MCP_TRANSPORT` | `sse` | `sse` or `streamable-http` |
| `MCP_API_TOKEN` | *(empty)* | Bearer token; when set, all HTTP routes require `Authorization: Bearer <token>` |
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

## ◈ Architecture

```
MCP Client (AI agent)
        │ HTTP/SSE
        ▼
┌─────────────────────────────────────────┐
│         Kali MCP Server (:8399)         │
│                                         │
│  ┌─────────────┐  ┌─────────────────┐   │
│  │ Token Auth  │  │ CORS Middleware │   │
│  │  (optional) │  │                 │   │
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

## 🧪 Tests & checks

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

## ⚠ Known limitations

- **Kali tools must be installed on the host.** The server wraps binaries like `nmap`, `sqlmap`, `hydra`; it does not install them. If a binary isn't in `PATH`, the tool returns a structured "Binary not found" error with an install hint.
- **`generic_command` runs arbitrary shell.** It's the escape hatch — use it deliberately. It is subject to the same timeout and semaphore limits as native tools.
- **In-memory monitor state.** The live monitor (sessions, active jobs) lives in memory and resets on server restart. Persisted data (SQLite, vault) survives restarts.
- **No alerting yet.** The monitor displays status but does not send alerts for stuck executions or high error rates.
- **Output truncation.** stdout/stderr are capped at 100 KB per stream to prevent memory exhaustion.

## ◈ Troubleshooting

| Symptom | Likely cause | Next step |
|---|---|---|
| Server won't start | Port 8399 in use | Set `MCP_PORT` to a free port |
| Tool returns "Binary not found" | Kali tool not installed or not in `PATH` | Install the tool or add it to `PATH` |
| `401 Unauthorized` | `MCP_API_TOKEN` set but no/invalid token | Provide `Authorization: Bearer <token>` or `?token=` query param |
| Monitor TUI shows no jobs | No executions currently running | Run a tool first; jobs appear while active |
| `q` doesn't quit TUI | Terminal rendering glitch | Press `q` again; if stuck, `Ctrl+C` |

## License

MIT

---

*Built with soft voltage — sharp security tooling wrapped in a warm, expressive MCP server.*