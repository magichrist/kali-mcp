"""Entry point for ``python -m kmcp``.

Usage:

    python -m kmcp                              # show help
    python -m kmcp --help                       # show help
    python -m kmcp start [--host HOST] [--port PORT]   # start the MCP server (alias: s)
    python -m kmcp monitor [<url>]              # launch the interactive monitor TUI (alias: m)
    python -m kmcp purge <scope> [--confirm]    # purge data: db | vault | all (alias: p)

The unified ``kmcp`` console script maps to :func:`kmcp.cli.main`.
"""

from __future__ import annotations

import sys

from kmcp.cli import main as cli_main


def main() -> None:
    argv = sys.argv[1:]
    sys.exit(cli_main(argv))


if __name__ == "__main__":
    main()
