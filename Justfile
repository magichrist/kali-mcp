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

# Run the full pytest suite (unit + integration)
test:
    .venv/bin/python -m pytest

# Run only fast unit tests
test-unit:
    .venv/bin/python -m pytest tests/unit

# Run integration tests (uses local subprocesses; no external binaries needed except coreutils)
test-integration:
    .venv/bin/python -m pytest tests/integration

# Run end-to-end protocol tests (spawns a real server)
test-e2e:
    .venv/bin/python -m pytest tests/e2e -m e2e

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

# Deploy to the Kali VM and restart the server (requires ssh key auth)
deploy host="kali-linux.shared" dest="~/kali-mcp":
    rsync -av --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
        --exclude 'logs' --exclude 'artifacts' --exclude 'data' \
        ./ {{host}}:{{dest}}/
    ssh {{host}} "pkill -f '[s]erver.py' || true; cd {{dest}} && \
        nohup python server.py > logs/stdout.log 2>&1 & sleep 2; \
        curl -sf --max-time 5 http://127.0.0.1:8399/sse -o /dev/null \
        && echo 'server restarted OK' || echo 'server did not come up — check logs/stdout.log'"
