"""Entry point for ``python -m kali_mcp``.

Runs the hardened SSE/streamable-http MCP server defined in
:mod:`kali_mcp.server`.
"""

from kali_mcp.server import main

if __name__ == "__main__":
    main()
