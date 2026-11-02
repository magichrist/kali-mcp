# Kali MCP Server

Production-grade MCP server that exposes Kali Linux penetration testing tools to AI agents via the Model Context Protocol (MCP).

## Quick Start

```bash
# Install dependencies
just install

# Start the server
just start

# Or with debug logging
just debug
```

The server runs on `http://0.0.0.0:8399/mcp` by default. Point your AI agent's MCP client at this URL to connect.

## Configuration

Copy `.env` and adjust values:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_HOST` | `0.0.0.0` | Listen address |
| `MCP_PORT` | `8399` | Listen port |
| `MCP_DEFAULT_TIMEOUT` | `300` | Default command timeout (seconds) |
| `MCP_MAX_TIMEOUT` | `3600` | Maximum allowed timeout |
| `MCP_MAX_CONCURRENT` | `10` | Max concurrent tool executions |
| `MCP_LOG_DIR` | `logs` | Log output directory |
| `MCP_ARTIFACT_DIR` | `artifacts` | Command output artifacts |
| `MCP_DEBUG` | `false` | Enable verbose debug logging |
| `MCP_VAULT_MAX_ROW_BYTES` | `26214400` | Max vault row size in bytes (25MB, `0` = unlimited) |

## Available Tools (56)

### General Execution

| Tool | Description |
|------|-------------|
| `generic_command` | Execute arbitrary shell commands on the Kali machine — the escape hatch for any tool not wrapped natively |
| `python_command` | Execute Python scripts directly on the Kali machine — access any installed Python library (scapy, impacket, requests, etc.) |
| `file_read` | Read files from the Kali machine |
| `file_write` | Write/create files on the Kali machine |
| `file_download` | Generate download links for files on the Kali machine |

### Reconnaissance & Enumeration

| Tool | Description |
|------|-------------|
| `nmap` | Network port scanner with service/version detection and NSE scripts |
| `naabu` | Fast TCP/UDP port scanner (SYN scan support) |
| `subfinder` | Passive subdomain discovery from multiple sources |
| `amass` | Attack surface mapping and deep subdomain enumeration |
| `theharvester` | Email, subdomain, and name harvesting from public sources |
| `spiderfoot` | OSINT automation and reconnaissance |
| `katana` | Web crawler and URL discovery |
| `farsight` | Domain intelligence — recon, asset discovery, threat intel, typosquat detection |
| `whatweb` | Web technology fingerprinting — CMS, frameworks, libraries, plugins |

### Web Application Testing

| Tool | Description |
|------|-------------|
| `httpx` | HTTP probing, technology detection, and web recon |
| `nuclei` | Template-based vulnerability scanner with severity filtering |
| `ffuf` | Web fuzzer — directory discovery, parameter fuzzing, vhost enumeration |
| `dursgo` | Full web app security scanner — XSS, SQLi, LFI, SSRF, IDOR, CSRF, CMDi, SSTI, CORS, file upload, BOLA, mass assignment, GraphQL, DOM XSS, subdomain discovery |
| `arjun` | HTTP parameter discovery — finds hidden GET/POST/JSON parameters |
| `sqlmap` | SQL injection detection and exploitation |
| `commix` | Command injection detection and exploitation |
| `wpscan` | WordPress vulnerability scanning and enumeration |
| `enum4linux` | SMB/Samba enumeration |

### Network & Infrastructure

| Tool | Description |
|------|-------------|
| `netexec` | Network protocol execution — SMB, WinRM, SSH, LDAP, RDP, MSSQL, FTP |
| `crackmapexec` | Network authentication testing and exploitation |
| `bloodhound` | Active Directory enumeration and attack path analysis |

### Security Analysis & Audit

| Tool | Description |
|------|-------------|
| `searchsploit` | Exploit-DB search — by keyword, CVE, or EDB-ID with exploit details |
| `flowlyt` | CI/CD pipeline security analyzer for GitHub/GitLab/Bitbucket workflows |
| `zizmor` | GitHub Actions workflow static security auditor |
| `zighound` | Red team network framework — network scanning, C2 listener, agent deployment, evasion simulation |

### Brute-Force & Cracking

| Tool | Description |
|------|-------------|
| `hydra` | Login brute-forcer — SSH, FTP, SMB, HTTP, and many more services |
| `medusa` | Parallelized login brute-forcer across many hosts/services |
| `hashcat` | GPU-accelerated password recovery and hash cracking |
| `john` | John the Ripper — password hash cracking |

### Directory & Content Discovery

| Tool | Description |
|------|-------------|
| `gobuster` | Directory, DNS, and vhost brute-force |
| `dirb` | Web content scanner with wordlist-based discovery |
| `wfuzz` | Web fuzzer for directories, parameters, and headers |

### Exploitation & Post-Exploitation

| Tool | Description |
|------|-------------|
| `msfconsole` | Metasploit Framework console via resource scripts |
| `bettercap` | MITM framework — sniffing, ARP/DNS spoofing, credential capture |
| `responder` | LLMNR/NBT-NS/MDNS poisoning — capture NTLM authentication hashes |
| `zap` | OWASP ZAP web application vulnerability scanning |

### Orchestration

| Tool | Description |
|------|-------------|
| `parallel_execute` | Run multiple tools concurrently, aggregate + deduplicate ports/vulns |
| `parallel_status` | Check status of a parallel_execute job |
| `playbook_recon` | Recon pipeline: subfinder → httpx → masscan → whatweb+nmap → nuclei |
| `playbook_webapp` | Web app pipeline: katana → arjun+ffuf → nuclei → sqlmap+commix |
| `playbook_ad` | AD pipeline: enum4linux → bloodhound → netexec+crackmapexec |
| `playbook_engine` | Run a custom multi-tool playbook with `{{target}}` substitution and resume |
| `playbook_list` | List available playbooks + last-run status |
| `playbook_status` | Check which playbook steps completed (resume support) |
| `health_check` | Server health and execution statistics |
| `force_cleanup` | Force-kill stuck subprocesses and clean the process tree |

### Persistence & Knowledge Sharing

Every tool run is automatically recorded:

- **SQLite** (`data/kali-mcp.sqlite`): targets, scans, findings, credentials
- **Vault** (`artifacts/vault/vault.sqlite`): SQLite-backed inter-agent row store — any agent or subagent can save, read, query, and delete rows (findings, credentials, evidence, notes, task/status rows) so work can be passed between agents
- Tools with structured output (hydra, medusa, john, hashcat, masscan, gobuster, dirb, wfuzz, responder, zap) parse their results into per-finding rows
- Browse via MCP resources: `kali://db/stats` and `kali://vault/index`

### Vault — Inter-Agent Data Sharing

| Tool | Description |
|------|-------------|
| `vault_write` | Upsert one row under (category, name) — unique row keys like `vuln:VULN-001`, `cred:<id>`, `sys:<host>`, `task:<stage>`. Content is the row's plain key=value fields (verbatim), a JSON object, or a JSON array. Tag rows with `agent:x`, `phase:n`, `severity:critical`, `superseded` |
| `vault_read` | Read a row's full content by category + name (exact pickup). Rows > `max_bytes` (default 1MB) come back truncated with `truncated: true`, `total_bytes`, and the mirror `path` — page through with `file_read(path, offset)` |
| `vault_query` | Search rows by one or more categories (comma-separated), target, tool, or free-text across names/tags/content |
| `vault_list` | List row metadata (newest-created first), optionally per category |
| `vault_delete` | Remove a row — **orchestrator-only** (stale `task:`/`status:` rows, superseded run rows) |
| `vault_stats` | Totals, per-category counts (`GROUP BY category`), per-tool counts, storage size |

Typical agent → subagent handoff: the parent agent runs a playbook, saves
rows via `vault_write` (`task:<stage>` rows for tasking, `status:<stage>`
rows for completion), and the subagent discovers them with `vault_query`
and reads them with `vault_read`. Exit rule for every agent: verify via
`vault_stats` + `vault_query` that your categories are populated and
queryable — never write files.

Storage model: canonical store is SQLite (`artifacts/vault/vault.sqlite`,
single `entries` table, UNIQUE(category, name), indexes on category/target/
tags, WAL). Each row is also mirrored to
`artifacts/vault/<category>/<name>.json` for human browsing, and
`artifacts/vault/index.json` is regenerated from SQLite after every write —
it can never drift or stay corrupt.

Limits & search semantics:
- Row size is capped at `MCP_VAULT_MAX_ROW_BYTES` (default 25MB, `0` =
  unlimited). Oversized writes are rejected with guidance to split the
  payload or store it as a file and record the path.
- `vault_query` search is literal substring matching, not tokenized —
  search for distinctive strings (hostnames, CVE IDs, ports, markers)
  rather than assuming a content format.

## Tool Details

### generic_command

The escape hatch for any command not covered by a native tool. Runs shell commands directly on the Kali machine.

```json
{
  "command": "nmap -sV 10.0.0.1",
  "timeout": 300,
  "cwd": "/tmp"
}
```

- Supports full bash scripting: pipes, redirects, here docs, functions, arrays, arithmetic
- Returns structured output: stdout, stderr, exit code, timing
- Timeout protection prevents hung commands

### python_command

Execute Python scripts on the Kali machine. This is a superpower — any Python library installed on the system is available.

```json
{
  "code": "import requests; r = requests.get('https://example.com'); print(r.status_code, len(r.text))"
}
```

- Runs as a standalone Python process with its own timeout
- Full access to system Python libraries
- Supports multi-line scripts with functions, classes, imports

### nmap

Network port scanner with full Nmap feature support.

```json
{
  "target": "10.0.0.1",
  "scan_type": "-sV -sC",
  "ports": "1-1000",
  "extra_args": "--script vuln"
}
```

### nuclei

Template-based vulnerability scanner. Scan targets against the full Nuclei template library.

```json
{
  "target": "https://example.com",
  "templates": "cves/",
  "severity": "critical,high"
}
```

### dursgo

Comprehensive web application security scanner with AI-powered analysis. Covers 16+ vulnerability classes in a single scan.

```json
{
  "target": "https://example.com",
  "scanners": "xss,sqli,lfi,ssrf,csrf",
  "render_js": true,
  "enable_ai": true,
  "enrich": true
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Client (AI Agent)                 │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP/SSE
┌───────────────────────▼─────────────────────────────────┐
│                  Kali MCP Server (:8399)                 │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Security │  │   Execution  │  │   Tool Registry   │  │
│  │          │  │   Engine     │  │                   │  │
│  │ Allowlist│  │ ┌──────────┐ │  │ 56 tools with    │  │
│  │ Input    │→ │ │ asyncio  │ │  │ validated schemas │  │
│  │ Validate │  │ │ timeout  │ │  │                   │  │
│  │ Sanitize │  │ │ watchdog │ │  └───────────────────┘  │
│  │ Block    │  │ │ semaphor │ │                         │
│  └──────────┘  │ └──────────┘ │                         │
│                └──────┬───────┘                         │
│                       │ subprocess                      │
│                ┌──────▼───────┐                         │
│                │  Kali Linux  │                         │
│                │  56 tools    │                         │
│                └──────────────┘                         │
└─────────────────────────────────────────────────────────┘
```

### Security Layers

1. **Allowlist** — Commands must match a strict allowlist pattern
2. **Input Validation** — Arguments validated against JSON schemas
3. **Shell Injection Prevention** — All arguments sanitized before execution
4. **Timeout Protection** — 3-layer defense: asyncio timeout, watchdog thread, semaphore
5. **Output Truncation** — stdout/stderr capped at 100KB to prevent memory exhaustion

### Resilience

- **3-layer timeout defense**: asyncio.wait_for → watchdog thread → semaphore
- **Automatic process cleanup**: Zombie processes killed via process tree termination
- **Concurrent execution limits**: Semaphore prevents resource exhaustion
- **Graceful degradation**: All errors return structured responses, never crash

## Testing

```bash
just test              # full suite: unit + integration + e2e
just purge db          # reset the main SQLite DB (targets/scans/findings/credentials)
just purge vault       # reset the vault store (SQLite + JSON mirrors + index)
just purge all         # reset both — asks first; skip the prompt with CONFIRM=1
```

The test suite lives under `tests/` and runs on **pytest** (requires the project `.venv`):

```bash
just test              # full suite: unit + integration + e2e
just test-unit         # fast, isolated tests
just test-integration  # engine + tool execution (async)
just test-e2e          # spawns a real server, speaks MCP over HTTP
```

| Layer | Location | What it covers |
|-------|----------|----------------|
| Unit | `tests/unit/` | Config, models, validators, registry, tool schemas, SQLite CRUD, vault |
| Integration | `tests/integration/` | Execution engine, generic/python/file tools, safe_execute, playbook engine |
| E2E | `tests/e2e/` | Boots `server.py` on a random port, verifies MCP handshake, tool inventory, and round-trip execution |

## Directory Structure

```
kali-mcp/
├── server.py              ← HTTP/SSE server, tool dispatch, health monitor
├── execution.py           ← 3-layer hardened execution engine
├── security.py            ← Allowlist, input validation, shell injection prevention
├── config.py              ← Configuration loading with validation
├── models.py              ← ExecutionResult, ToolError, ToolDefinition dataclasses
├── responses.py           ← Standardized JSON response builders
├── registry.py            ← Tool registration and lookup
├── logging_utils.py       ← Structured logging with execution tracking
├── utils/
│   └── process.py         ← Process tree cleanup
├── tools/
│   ├── __init__.py        ← Tool registration
│   ├── base.py            ← BaseTool ABC — all tools extend this
│   ├── generic_command.py ← GenericCommandTool — shell escape hatch
│   ├── python_command.py  ← PythonCommandTool — Python execution
│   ├── file_read.py       ← FileReadTool — file reading
│   ├── file_write.py      ← FileWriteTool — file writing
│   ├── file_download.py   ← FileDownloadTool — file download links
│   ├── nmap.py            ← NmapTool — port scanner
│   ├── httpx.py           ← HttpxTool — HTTP probing
│   ├── nuclei.py          ← NucleiTool — vuln scanner
│   ├── ffuf.py            ← FfufTool — web fuzzer
│   ├── katana.py          ← KatanaTool — web crawler
│   ├── subfinder.py       ← SubfinderTool — subdomain discovery
│   ├── amass.py           ← AmassTool — attack surface mapping
│   ├── sqlmap.py          ← SqlmapTool — SQL injection
│   ├── commix.py          ← CommixTool — command injection
│   ├── wpscan.py          ← WpscanTool — WordPress scanner
│   ├── enum4linux.py      ← Enum4linuxTool — SMB enumeration
│   ├── netexec.py         ← NetexecTool — network protocol execution
│   ├── crackmapexec.py    ← CrackmapexecTool — network auth testing
│   ├── bloodhound.py      ← BloodhoundTool — AD enumeration
│   ├── theharvester.py    ← TheharvesterTool — OSINT harvesting
│   ├── spiderfoot.py      ← SpiderfootTool — OSINT automation
│   ├── naabu.py           ← NaabuTool — fast port scanner
│   ├── arjun.py           ← ArjunTool — parameter discovery
│   ├── whatweb.py         ← WhatwebTool — technology fingerprinting
│   ├── dursgo.py          ← DursgoTool — web app scanner
│   ├── zighound.py        ← ZighoundTool — red team framework
│   ├── searchsploit.py    ← SearchsploitTool — exploit search
│   ├── farsight.py        ← FarsightTool — domain intelligence
│   ├── flowlyt.py         ← FlowlytTool — CI/CD security
│   ├── zizmor.py          ← ZizmorTool — GitHub Actions audit
│   ├── msfconsole.py      ← MsfconsoleTool — Metasploit
│   ├── hydra.py           ← HydraTool — login brute-force
│   ├── hashcat.py         ← HashcatTool — GPU hash cracking
│   ├── john.py            ← JohnTool — password cracking
│   ├── gobuster.py        ← GobusterTool — directory brute-force
│   ├── dirb.py            ← DirbTool — web content scanner
│   ├── wfuzz.py           ← WfuzzTool — web fuzzer
│   ├── medusa.py          ← MedusaTool — parallel brute-force
│   ├── masscan.py         ← MasscanTool — masscan port scanner
│   ├── zap.py             ← ZapTool — OWASP ZAP scanner
│   ├── bettercap.py       ← BettercapTool — MITM framework
│   ├── responder.py       ← ResponderTool — LLMNR poisoning
│   ├── parallel_execute.py← ParallelExecuteTool + ParallelStatusTool — fan-out
│   ├── playbook_engine.py ← PlaybookEngine — state tracking, resume, {{target}} substitution
│   ├── playbook_recon.py  ← PlaybookReconTool — recon pipeline
│   ├── playbook_webapp.py ← PlaybookWebappTool — web app pipeline
│   ├── playbook_ad.py     ← PlaybookAdTool — AD pipeline
│   ├── playbook_tools.py  ← PlaybookListTool + PlaybookStatusTool
│   ├── persist.py         ← Shared persistence + per-tool output parsers
│   ├── vault_tool.py      ← vault_write/read/query/list/delete/stats MCP tools
│   └── normalization.py   ← NormalizedToolMixin — per-tool output schema
├── db/
│   └── manager.py         ← SQLite persistence: targets, scans, findings, creds
├── utils/
│   ├── process.py         ← Process tree cleanup
│   └── vault.py           ← SQLite-backed inter-agent vault
├── tests/
│   ├── conftest.py        ← Shared fixtures + global registry wiring
│   ├── unit/              ← Fast isolated tests (schemas, validation, DB, vault)
│   ├── integration/       ← Async engine + tool execution tests
│   └── e2e/               ← Spawns a real server, speaks MCP over HTTP
├── pytest.ini
├── requirements.txt
├── Justfile
├── logs/
├── artifacts/
├── data/                   ← SQLite DB (kali-mcp.sqlite)
└── .env
```
