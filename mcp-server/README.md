# Kali MCP Server

Production-grade MCP server for AI penetration testing agents.

## Quick Start

```bash
pip install -r requirements.txt
python server.py
```

Server runs on `http://0.0.0.0:8399/sse` by default.

## Configuration

All settings via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_HOST` | `0.0.0.0` | Listen address |
| `MCP_PORT` | `8399` | Listen port |
| `MCP_DEFAULT_TIMEOUT` | `300` | Default command timeout |
| `MCP_MAX_TIMEOUT` | `3600` | Maximum allowed timeout |
| `MCP_MAX_CONCURRENT` | `10` | Max concurrent executions |
| `MCP_DEBUG` | `false` | Debug logging |

## Tools

### Native Tools
`nmap`, `httpx`, `nuclei`, `ffuf`, `katana`, `subfinder`, `amass`, `sqlmap`, `commix`, `wpscan`, `enum4linux`, `netexec`, `crackmapexec`, `bloodhound`, `theharvester`, `spiderfoot`

### Escape Hatch
`generic_command` — execute any arbitrary command.

## Adding a New Tool

1. Create `tools/your_tool.py` inheriting from `BaseTool`
2. Add to `tools/__init__.py` imports and `ALL_TOOLS`
3. Done. <30 lines.

## Architecture

- **FastMCP** — SSE transport layer
- **ToolRegistry** — maps names to tool instances
- **BaseTool** — ABC all tools implement
- **ExecutionEngine** — single subprocess execution layer
- **Validation** — parameter validators
- **Structured JSON** — every response is deterministic
