# Kali MCP Server — Just Commands
set dotenv-load

# Show available commands
default:
    @just --list

# Install dependencies
install:
    pip install -r requirements.txt

# Start the server (foreground)
start:
    python server.py

# Start in debug mode
debug:
    MCP_DEBUG=true python server.py

# Run smoke tests
test:
    python test_server.py

# Show server health (requires running server)
health:
    @curl -sf http://127.0.0.1:8399/sse -o /dev/null && echo "Server running" || echo "Server not running"

# View logs
logs:
    tail -f logs/server.log

# View execution logs
exec-logs:
    tail -f logs/executions.jsonl

# Clean build artifacts
clean:
    rm -rf logs/*.log logs/*.jsonl
    rm -rf artifacts/*
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Show all registered tools
tools:
    python -c "from tools import ALL_TOOLS; [print(f'  {t.name:20s} {t.description[:60]}') for t in ALL_TOOLS]"
