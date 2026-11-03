"""Entry point for ``python -m kali_mcp``.

Usage:

    python -m kali_mcp              # start the MCP server (SSE/streamable-http)
    python -m kali_mcp monitor      # launch the interactive monitor TUI
    python -m kali_mcp monitor <url># monitor a server at a custom base URL
"""

from __future__ import annotations

import sys

from kali_mcp.server import main as server_main
from kali_mcp.monitor.tui import main as monitor_main


def main() -> None:
    argv = sys.argv[1:]

    if argv and argv[0] == "monitor":
        url = argv[1] if len(argv) > 1 else "http://127.0.0.1:8399"
        monitor_main(url)
    else:
        server_main()


if __name__ == "__main__":
    main()
