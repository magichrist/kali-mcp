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

## Available Tools (30)

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
│  │ Allowlist│  │ ┌──────────┐ │  │ 30 tools with    │  │
│  │ Input    │→ │ │ asyncio  │ │  │ validated schemas │  │
│  │ Validate │  │ │ timeout  │ │  │                   │  │
│  │ Sanitize │  │ │ watchdog │ │  └───────────────────┘  │
│  │ Block    │  │ │ semaphor │ │                         │
│  └──────────┘  │ └──────────┘ │                         │
│                └──────┬───────┘                         │
│                       │ subprocess                      │
│                ┌──────▼───────┐                         │
│                │  Kali Linux  │                         │
│                │  30 tools    │                         │
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
│   └── zizmor.py          ← ZizmorTool — GitHub Actions audit
├── tests/
├── logs/
├── artifacts/
├── .env
├── justfile
├── pyproject.toml
└── uv.lock
```
