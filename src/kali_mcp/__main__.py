"""Entry point for ``python -m kali_mcp``.

Usage:

    python -m kali_mcp                              # start the MCP server (default)
    python -m kali_mcp start [--host HOST] [--port PORT]   # start the MCP server (alias: s)
    python -m kali_mcp monitor [<url>]              # launch the interactive monitor TUI (alias: m)
    python -m kali_mcp purge <scope> [--confirm]    # purge data: db | vault | all (alias: p)

The unified ``kmcp`` console script maps to :func:`kali_mcp.cli.main`.
"""

from __future__ import annotations

import sys

from kali_mcp.cli import main as cli_main


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        argv = ["start"]
    sys.exit(cli_main(argv))


if __name__ == "__main__":
    main()
