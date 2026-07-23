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

## Available Tools (23)

### Reconnaissance

| Tool | Description |
|------|-------------|
| `nmap` | Network port scanner with service/version detection |
| `naabu` | Fast TCP/UDP port scanner (SYN scan support) |
| `subfinder` | Passive subdomain discovery |
| `amass` | Attack surface mapping and subdomain enumeration |
| `theharvester` | Email, subdomain, and name harvesting from public sources |
| `spiderfoot` | OSINT automation and reconnaissance |
| `katana` | Web crawler and URL discovery |

### Web Application

| Tool | Description |
|------|-------------|
| `httpx` | HTTP probing, technology detection, and web recon |
| `nuclei` | Template-based vulnerability scanner |
| `ffuf` | Web fuzzer — directory discovery, parameter fuzzing |
| `whatweb` | Web technology fingerprinting (CMS, frameworks, libraries) |
| `arjun` | HTTP parameter discovery — finds hidden GET/POST/JSON params |

### Vulnerability Assessment

| Tool | Description |
|------|-------------|
| `sqlmap` | SQL injection detection and exploitation |
| `commix` | Command injection detection and exploitation |
| `wpscan` | WordPress vulnerability scanner |

### Active Directory

| Tool | Description |
|------|-------------|
| `enum4linux` | SMB/Samba enumeration |
| `netexec` | Network protocol execution (SMB, WinRM, SSH, LDAP, RDP) |
| `crackmapexec` | Legacy CME wrapper (routes to netexec if unavailable) |
| `bloodhound` | SharpHound/BloodHound AD collection |

### File Operations

| Tool | Description |
|------|-------------|
| `file_read` | Read files from the Kali machine with offset and truncation support |
| `file_write` | Create/write files on the Kali machine (auto-creates directories) |

### Generic Execution

| Tool | Description |
|------|-------------|
| `generic_command` | Execute arbitrary shell commands (pipes, redirects, `&&` supported) |
| `python_command` | Execute Python code directly (imports, loops, data processing) |

## Adding a New Tool

Creating a new tool takes ~30 lines. Here's the full process:

### 1. Create the tool file

Create `mcp-server/tools/your_tool.py`:

```python
"""YourTool description."""

from __future__ import annotations
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response


class YourTool(BaseTool):
    @property
    def name(self) -> str:
        return "yourtool"  # CLI name of the tool on the Kali machine

    @property
    def description(self) -> str:
        return "Human-readable description shown to the AI agent."

    @property
    def default_timeout(self) -> int:
        return 300  # seconds

    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for tool parameters. Becomes the tool's input contract."""
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "What to scan",
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional CLI arguments (e.g. '-v --output json')",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 300,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        """Validate inputs before building command. Raise ValueError on bad input."""
        validate_required(arguments, "target")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        """Convert validated arguments into a command list (no shell injection)."""
        cmd = ["yourtool", arguments["target"]]
        if "extra_args" in arguments:
            cmd.extend(arguments["extra_args"].split())
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run the tool via the execution engine."""
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))

        result = await engine.execute(
            command=self.build_command(arguments),
            tool=self.name,
            timeout=arguments.get("timeout", self.default_timeout),
        )
        return success_response(result)
```

### 2. Register it

Add to `mcp-server/tools/__init__.py`:

```python
from tools.your_tool import YourTool  # add this import
```

And append to `ALL_TOOLS`:

```python
ALL_TOOLS = [
    # ... existing tools ...
    YourTool(),  # add this line
]
```

### 3. Verify

```bash
cd mcp-server
python3 -c "from tools.your_tool import YourTool; t = YourTool(); print(t.name, t.description)"
just test  # run smoke tests
```

That's it. The server auto-registers it on next start.

## Available Validators

Use these in your `validate()` method:

| Validator | Usage |
|-----------|-------|
| `validate_required(args, "field")` | Ensure field is present |
| `validate_ip("10.0.0.1")` | Validate IPv4 address |
| `validate_cidr("10.0.0.0/24")` | Validate CIDR notation |
| `validate_domain("example.com")` | Validate domain name |
| `validate_url("https://example.com")` | Validate full URL |
| `validate_enum(value, ["a","b"])` | Validate against allowed values |
| `validate_timeout(seconds)` | Validate timeout bounds |
| `validate_ports("80,443,1-1024")` | Validate port specification |

## Architecture

```
┌─────────────────────────────────────────────────┐
│  AI Agent (Claude, GPT, Gemini, etc.)           │
└────────────────────┬────────────────────────────┘
                     │ MCP (SSE)
┌────────────────────▼────────────────────────────┐
│  FastMCP Server (server.py)                     │
│  ┌──────────────┐  ┌─────────────────────────┐  │
│  │ ToolRegistry │  │ Health Check             │  │
│  └──────┬───────┘  └─────────────────────────┘  │
│         │                                        │
│  ┌──────▼──────────────────────────────────┐     │
│  │ Tools (20 native + generic_command)     │     │
│  │  validate → build_command → execute     │     │
│  └──────┬──────────────────────────────────┘     │
│         │                                        │
│  ┌──────▼──────────────────────────────────┐     │
│  │ ExecutionEngine (async subprocess)      │     │
│  │  semaphore → run → log → return         │     │
│  └──────┬──────────────────────────────────┘     │
│         │                                        │
│  ┌──────▼──────────────────────────────────┐     │
│  │ Structured JSON Response                │     │
│  │  stdout, stderr, exit_code, timing      │     │
│  └─────────────────────────────────────────┘     │
└─────────────────────────────────────────────────┘
```

## Just Commands

```
just install    — Install Python dependencies
just start      — Start the server (foreground)
just debug      — Start with debug logging
just test       — Run smoke tests
just health     — Check if server is running
just logs       — Tail server logs
just exec-logs  — Tail execution audit logs
just tools      — List all registered tools
just clean      — Clear logs and artifacts
```

## Project Structure

```
mcp-server/
├── server.py              ← Entry point — FastMCP SSE server
├── config.py              ← Environment-based configuration
├── models.py              ← ExecutionResult, ToolError dataclasses
├── execution.py           ← Async subprocess execution engine
├── validation.py          ← Input validators (IP, domain, URL, etc.)
├── logging_utils.py       ← Structured JSON logging
├── responses.py           ← MCP response builders
├── security.py            ← Command sanitization
├── registry.py            ← Tool name → instance registry
├── requirements.txt       ← Python dependencies
├── test_server.py         ← Smoke tests
├── tools/
│   ├── __init__.py        ← Auto-imports all tools
│   ├── base.py            ← BaseTool abstract class
│   ├── generic_command.py ← Escape hatch
│   ├── nmap.py            ├── naabu.py
│   ├── httpx.py           ├── nuclei.py
│   ├── ffuf.py            ├── katana.py
│   ├── subfinder.py       ├── amass.py
│   ├── sqlmap.py          ├── commix.py
│   ├── wpscan.py          ├── whatweb.py
│   ├── arjun.py           ├── enum4linux.py
│   ├── netexec.py         ├── crackmapexec.py
│   ├── bloodhound.py      ├── theharvester.py
│   └── spiderfoot.py
├── utils/
│   └── process.py         ← Kill process tree helper
├── logs/                  ← Runtime logs
└── artifacts/             ← Command output artifacts
```
