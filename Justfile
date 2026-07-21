# Kali MCP Server

default:
	@just --list

# Start the MCP server
run:
	cd mcp-server && python server.py

# Start in debug mode
debug:
	cd mcp-server && MCP_DEBUG=true python server.py

# Install dependencies
install:
	cd mcp-server && pip install -r requirements.txt

# Run smoke tests
test:
	cd mcp-server && python test_server.py

# Clean logs and artifacts
clean:
	rm -rf mcp-server/logs/* mcp-server/artifacts/*

# Show server status
status:
	@echo "=== Kali MCP Server ==="
	@echo "Tools: $(cd mcp-server && python3 -c 'from registry import registry; from tools import ALL_TOOLS; print(len(ALL_TOOLS))')"
	@echo "Port: 8399"
