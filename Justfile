# Kali MCP Server — Just Commands

set dotenv := true

# Show available commands
default:
    @just --list

# Install dependencies
install:
    cd mcp-server && pip install -r requirements.txt

# Start the server (foreground)
start:
    cd mcp-server && python server.py

# Start in debug mode
debug:
    cd mcp-server && MCP_DEBUG=true python server.py

# Run smoke tests
test:
    cd mcp-server && python test_server.py

# Show server health (requires running server)
health:
    curl -s http://127.0.0.1:8399/health 2>/dev/null || echo "Server not running"

# View logs
logs:
    tail -f mcp-server/logs/server.log

# View execution logs
exec-logs:
    tail -f mcp-server/logs/executions.jsonl

# Clean build artifacts
clean:
    rm -rf mcp-server/logs/*.log mcp-server/logs/*.jsonl
    rm -rf mcp-server/artifacts/*
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Show all registered tools (requires running server)
tools:
    cd mcp-server && python -c "from tools import ALL_TOOLS; [print(f'  {t.name:20s} {t.description[:60]}') for t in ALL_TOOLS]"
