"""Kali MCP CLI — unified entry point for server, monitor, and data purge.

Usage:

    kmcp start [--host HOST] [--port PORT]   # start the MCP server (alias: s)
    kmcp monitor [URL]                        # launch the monitor TUI (alias: m)
    kmcp purge SCOPE [--confirm]              # purge data: db | vault | all (alias: p)

Environment variables (MCP_HOST, MCP_PORT, etc.) are read from .env via python-dotenv,
just like ``just start``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency missing # noqa: BLE001

    def load_dotenv(*args, **kwargs):
        return None


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_env() -> None:
    """Load .env from the repo root (idempotent)."""
    load_dotenv(str(REPO_ROOT / ".env"), override=False)


def cmd_start(args: argparse.Namespace) -> int:
    """Start the MCP server."""
    _load_env()
    os.environ.setdefault("MCP_HOST", args.host or os.getenv("MCP_HOST", "127.0.0.1"))
    os.environ.setdefault("MCP_PORT", args.port or os.getenv("MCP_PORT", "8399"))

    from kali_mcp.server import main

    main()
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    """Launch the interactive monitor TUI."""
    _load_env()
    url = args.url or os.getenv("MCP_MONITOR_URL", "http://127.0.0.1:8399")

    from kali_mcp.monitor.tui import main as monitor_main

    monitor_main(url)
    return 0


def _confirm(prompt: str) -> bool:
    """Ask the user for confirmation. Returns True on 'y'/'yes'."""
    try:
        response = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\naborted")
        return False
    return response in ("y", "yes")


def cmd_purge(args: argparse.Namespace) -> int:
    """Purge stored data (SQLite DB and/or vault)."""
    _load_env()

    scope = args.scope.lower()

    valid = {"db", "vault", "all"}
    if scope not in valid:
        print(f"unknown scope '{scope}' — use: db | vault | all", file=sys.stderr)
        return 1

    if not args.confirm and not _confirm(f"Purge '{scope}' data — this cannot be undone"):
        print("aborted")
        return 1

    removed: list[str] = []

    def rm(path: Path) -> None:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            removed.append(str(path))

    if scope in ("db", "all"):
        for name in ("kali-mcp.sqlite", "kali-mcp.sqlite-wal", "kali-mcp.sqlite-shm"):
            rm(REPO_ROOT / "data" / name)

    if scope in ("vault", "all"):
        rm(REPO_ROOT / "artifacts" / "vault")

    print(f"purged: {scope}")
    if removed:
        print("removed:")
        for path in removed:
            print(f"  {path}")
    else:
        print("nothing to remove")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kmcp",
        description="Kali MCP Server CLI — server, monitor, and data purge utilities.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start / s
    p_start = sub.add_parser("start", aliases=["s"], help="Start the MCP server")
    p_start.add_argument(
        "--host", default=None, help="Listen address (default: MCP_HOST or 0.0.0.0)"
    )
    p_start.add_argument("--port", default=None, help="Listen port (default: MCP_PORT or 8399)")
    p_start.set_defaults(func=cmd_start)

    # monitor / m
    p_monitor = sub.add_parser("monitor", aliases=["m"], help="Launch the monitor TUI")
    p_monitor.add_argument(
        "url",
        nargs="?",
        default=None,
        help="Base URL of the MCP server (default: http://127.0.0.1:8399)",
    )
    p_monitor.set_defaults(func=cmd_monitor)

    # purge / p
    p_purge = sub.add_parser("purge", aliases=["p"], help="Purge stored data")
    p_purge.add_argument(
        "scope",
        choices=["db", "vault", "all"],
        help="What to purge: db (SQLite), vault (artifacts/vault), or all",
    )
    p_purge.add_argument(
        "--confirm",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    p_purge.set_defaults(func=cmd_purge)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["start"]
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
