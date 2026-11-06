"""Kali MCP CLI — unified entry point for server, monitor, data purge,
and Playbook Studio management.

Usage:

    kmcp                                  # show help
    kmcp --help                           # show help
    kmcp start [--host HOST] [--port PORT]   # start the MCP server (alias: s)
    kmcp monitor [URL]                        # launch the monitor TUI (alias: m)
    kmcp purge SCOPE [--confirm]              # purge data: db | vault | all (alias: p)
    kmcp studio [--no-browser]                # open the Studio UI in a browser,
                                              # starting the server if needed (alias: st)

    kmcp playbook list [--status STATUS]                 # list playbooks
    kmcp playbook create --id ID --name NAME             # create a draft playbook
    kmcp playbook show ID                                # get playbook metadata + latest definition
    kmcp playbook validate ID [--definition FILE] [--for-publish]
    kmcp playbook preview ID [--definition FILE]         # dry-run a playbook
    kmcp playbook test ID [--definition FILE]            # controlled test execution
    kmcp playbook publish ID --version V [--definition FILE] [--notes N]
    kmcp playbook versions ID                            # list version history
    kmcp playbook rollback ID --version-id VID           # roll back to a version
    kmcp playbook export ID [--out FILE]                 # export playbook package
    kmcp playbook import FILE [--require-approval]       # import playbook package
    kmcp playbook seed                                   # seed built-in YAML playbooks

    kmcp tool list [--provider P] [--visibility V] [--enabled E]
    kmcp tool visibility ID MODE                         # set tool visibility

    kmcp execution list [--status S] [--playbook-id ID]
    kmcp execution cancel ID

Environment variables (MCP_HOST, MCP_PORT, etc.) are read from .env via python-dotenv,
just like ``just start``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import webbrowser
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


# ── helpers ──────────────────────────────────────────────────────────────


def _get_db():
    """Return the DB manager singleton."""
    from kali_mcp.db import manager as db_manager

    return db_manager.get_db()


def _print_table(rows: list[list[str]], headers: list[str]) -> None:
    """Print a simple text table."""
    if not rows:
        print("(no rows)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt(row):
        return "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))

    print(fmt(headers))
    print(fmt(["-" * w for w in widths]))
    for row in rows:
        print(fmt(row))


def _json_or_file(value: str | None) -> dict | None:
    """Parse a JSON string or load a JSON file.

    Tries JSON parsing first (so long JSON strings don't get misinterpreted
    as file paths), then falls back to reading from disk.
    """
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        pass
    p = Path(value)
    if p.exists():
        return json.loads(p.read_text())
    raise ValueError(f"not valid JSON and file not found: {value!r}")


# ── command handlers ─────────────────────────────────────────────────────


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


def _normalize_frontend_url(url: str) -> str:
    """Ensure a URL points at the Playbook Studio frontend."""
    url = (url or "").strip()
    if not url:
        return url
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path = (parsed.path or "").rstrip("/")
        if path in ("", "/"):
            url = url.rstrip("/") + "/studio"
    except Exception:  # noqa: BLE001
        if not url.rstrip("/").endswith("/studio"):
            url = url.rstrip("/") + "/studio"
    return url


def _open_frontend(args: argparse.Namespace) -> int:
    """Open the Playbook Studio frontend in the default browser."""
    _load_env()

    url = getattr(args, "url", None)
    if url:
        url = str(url).strip()
    else:
        host = getattr(args, "host", None) or os.getenv("MCP_HOST", "127.0.0.1")
        port = (
            getattr(args, "port", None)
            or os.getenv("STUDIO_PORT", "")
            or os.getenv("MCP_PORT", "")
            or "8399"
        )
        if host in ("0.0.0.0", "::", "", None):
            host = "127.0.0.1"
        url = f"http://{host}:{port}/studio"

    no_browser = bool(getattr(args, "no_browser", False) or getattr(args, "no_open", False))
    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    print(f"Frontend: {url}")
    return 0


# Aliases for the frontend command (all delegate to _open_frontend).
cmd_studio = _open_frontend
cmd_frontend = _open_frontend
cmd_web = _open_frontend
cmd_ui = _open_frontend
cmd_browser = _open_frontend
cmd_open = _open_frontend
cmd_gui = _open_frontend
cmd_dashboard = _open_frontend
cmd_webui = _open_frontend
cmd_open_frontend = _open_frontend
cmd_start_frontend = _open_frontend
cmd_frontend_browser = _open_frontend


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


# ── Studio (browser) commands ────────────────────────────────────────────


def _server_reachable(url: str, timeout: float = 1.5) -> bool:
    """Return True if the MCP server responds at ``url`` (any status < 500)."""
    import httpx

    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        return resp.status_code < 500
    except httpx.HTTPError:
        return False


def _wait_for_server(url: str, proc: subprocess.Popen, timeout: float = 25.0) -> bool:
    """Poll until the server answers, the child process dies, or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _server_reachable(url, timeout=1.0):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.25)
    return False


def cmd_studio(args: argparse.Namespace) -> int:
    """Open the Playbook Studio web UI in a browser.

    If the MCP server is already running at the target host:port, the
    browser is opened straight away. Otherwise the server is started in
    the foreground (as a child process) and the browser is opened once
    it is ready. The server keeps running until Ctrl+C.
    """
    _load_env()

    url_arg = (getattr(args, "url", None) or "").strip()
    if url_arg:
        url = _normalize_frontend_url(url_arg)
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or int(os.getenv("MCP_PORT", "8399"))
    else:
        host = getattr(args, "host", None) or os.getenv("MCP_HOST", "127.0.0.1")
        port = int(getattr(args, "port", None) or os.getenv("MCP_PORT", "8399"))
        url = f"http://{host}:{port}/studio"

    started_child = False
    child: subprocess.Popen | None = None
    if _server_reachable(url):
        print(f"server already running at http://{host}:{port}")
    else:
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "kali_mcp",
                "start",
                "--host",
                str(host),
                "--port",
                str(port),
            ]
        )
        started_child = True
        print(f"starting MCP server at http://{host}:{port} ...")
        if not _wait_for_server(url, child):
            if child.poll() is not None:
                print(
                    f"error: server exited with code {child.returncode} before it became ready",
                    file=sys.stderr,
                )
                return child.returncode or 1
            print(
                f"error: server did not become ready at {url} — is MCP_API_TOKEN set?",
                file=sys.stderr,
            )
            child.terminate()
            return 1

    print(f"Playbook Studio: {url}")
    if not getattr(args, "no_browser", False):
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 -- browser may be unavailable on headless hosts
            print("could not open a browser — open the URL manually", file=sys.stderr)

    if started_child:
        try:
            child.wait()
        except KeyboardInterrupt:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                child.kill()
            print("\nserver stopped")
    return 0


# ── Playbook Studio commands ─────────────────────────────────────────────


def cmd_playbook_list(args: argparse.Namespace) -> int:
    """List playbooks."""
    from kali_mcp.studio.playbook_service import list_playbooks

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    rows = list_playbooks(db, status=args.status)
    table = [
        [
            r.get("playbook_id", ""),
            r.get("name", "")[:40],
            r.get("status", ""),
            r.get("category", "") or "-",
            str(r.get("current_version_id") or "-"),
        ]
        for r in rows
    ]
    _print_table(
        table, ["playbook_id", "name", "status", "category", "current_version"]
    )
    return 0


def cmd_playbook_create(args: argparse.Namespace) -> int:
    """Create a draft playbook."""
    from kali_mcp.studio.playbook_service import create_playbook

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    try:
        row = create_playbook(
            db,
            playbook_id=args.id,
            name=args.name,
            description=args.description,
            category=args.category,
            author=args.author,
            status="draft",
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created playbook '{args.id}' (name: {args.name})")
    return 0


def cmd_playbook_show(args: argparse.Namespace) -> int:
    """Get playbook metadata + latest definition."""
    from kali_mcp.studio.playbook_service import get_playbook, get_version

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    row = get_playbook(db, args.id)
    if row is None:
        print(f"playbook '{args.id}' not found", file=sys.stderr)
        return 1
    print(f"id:        {row.get('playbook_id')}")
    print(f"name:      {row.get('name')}")
    print(f"status:    {row.get('status')}")
    print(f"category:  {row.get('category') or '-'}")
    print(f"author:    {row.get('author') or '-'}")
    print(f"builtin:   {bool(row.get('is_builtin', 0))}")
    vid = row.get("current_version_id")
    if vid:
        vrow = get_version(db, vid)
        if vrow:
            print(f"version:   {vrow.get('version')} (version_id: {vrow.get('version_id')})")
            print(f"published: {vrow.get('published_at') or '-'}")
            if vrow.get("notes"):
                print(f"notes:     {vrow.get('notes')}")
            definition = vrow.get("definition")
            if isinstance(definition, str):
                definition = json.loads(definition)
            print("definition:")
            print(json.dumps(definition, indent=2))
    else:
        print("version:   (none published)")
    return 0


def cmd_playbook_validate(args: argparse.Namespace) -> int:
    """Validate a playbook definition."""
    from kali_mcp.studio.playbook_service import validate_definition

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    definition = _json_or_file(args.definition)
    if definition is None:
        print("error: --definition is required (JSON string or file path)", file=sys.stderr)
        return 1
    result = validate_definition(db, args.id, definition, for_publish=args.for_publish)
    print(f"valid: {result['valid']}")
    findings = result.get("findings", [])
    if findings:
        print(f"findings ({len(findings)}):")
        for f in findings:
            print(f"  [{f.get('severity')}] {f.get('step_id') or '-'}:{f.get('field') or '-'} {f.get('message')}")
    else:
        print("no findings")
    return 0 if result["valid"] else 1


def cmd_playbook_preview(args: argparse.Namespace) -> int:
    """Dry-run a playbook (no execution)."""
    from kali_mcp.studio.playbook_service import preview_playbook

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    definition = _json_or_file(args.definition)
    if definition is None:
        print("error: --definition is required (JSON string or file path)", file=sys.stderr)
        return 1
    result = preview_playbook(db, args.id, definition)
    if not result.get("ok"):
        print(f"error: {result.get('error')}", file=sys.stderr)
        return 1
    print(f"playbook: {result.get('playbook_id')}")
    print(f"steps: {result.get('step_count')}")
    print(f"max_parallel: {result.get('max_parallel')}")
    print(f"timeout: {result.get('timeout')}")
    print("execution order:")
    for sid in result.get("execution_order", []):
        deps = result.get("dependencies", {}).get(sid, [])
        print(f"  {sid} (depends_on: {', '.join(deps) or '-'})")
    return 0


def cmd_playbook_test(args: argparse.Namespace) -> int:
    """Controlled test execution (mocked tools)."""
    from kali_mcp.studio.playbook_service import test_playbook

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    definition = _json_or_file(args.definition)
    if definition is None:
        print("error: --definition is required (JSON string or file path)", file=sys.stderr)
        return 1
    result = test_playbook(db, args.id, definition)
    if not result.get("ok"):
        print(f"error: {result.get('error')}", file=sys.stderr)
        return 1
    payload = result.get("payload", {})
    print(f"status: {payload.get('status')}")
    print(f"steps run: {len(payload.get('results', []))}")
    return 0


def cmd_playbook_publish(args: argparse.Namespace) -> int:
    """Publish an immutable playbook version."""
    from kali_mcp.studio.playbook_service import publish_version, validate_definition

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    definition = _json_or_file(args.definition)
    if definition is None:
        print("error: --definition is required (JSON string or file path)", file=sys.stderr)
        return 1

    # Validate first (publish-time rules)
    validation = validate_definition(db, args.id, definition, for_publish=True)
    if not validation["valid"]:
        print("definition failed validation:", file=sys.stderr)
        for f in validation.get("findings", []):
            print(f"  [{f.get('severity')}] {f.get('step_id') or '-'}:{f.get('field') or '-'} {f.get('message')}", file=sys.stderr)
        return 1

    try:
        vid = publish_version(
            db,
            playbook_id=args.id,
            version=args.version,
            definition=definition,
            notes=args.notes,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"published version '{args.version}' (version_id: {vid})")
    return 0


def cmd_playbook_versions(args: argparse.Namespace) -> int:
    """List version history for a playbook."""
    from kali_mcp.studio.playbook_service import list_versions

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    versions = list_versions(db, args.id)
    if not versions:
        print("(no versions)")
        return 0
    table = [
        [str(v.get("id")), v.get("version_id", ""), v.get("version", ""), v.get("published_at") or "-", v.get("notes") or "-"]
        for v in versions
    ]
    _print_table(table, ["id", "version_id", "version", "published_at", "notes"])
    return 0


def cmd_playbook_rollback(args: argparse.Namespace) -> int:
    """Roll back to an earlier published version."""
    from kali_mcp.studio.playbook_service import rollback_version

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    try:
        row = rollback_version(db, args.id, args.version_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"rolled back '{args.id}' to version '{row.get('version')}' (version_id: {row.get('version_id')})")
    return 0


def cmd_playbook_export(args: argparse.Namespace) -> int:
    """Export a playbook package."""
    from kali_mcp.studio.playbook_service import export_playbook

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    package = export_playbook(db, args.id)
    if package is None:
        print(f"playbook '{args.id}' not found", file=sys.stderr)
        return 1
    out = json.dumps(package, indent=2)
    if args.out:
        Path(args.out).write_text(out)
        print(f"exported to {args.out}")
    else:
        print(out)
    return 0


def cmd_playbook_import(args: argparse.Namespace) -> int:
    """Import a playbook package."""
    from kali_mcp.studio.playbook_service import import_playbook

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    package = json.loads(Path(args.file).read_text())
    result = import_playbook(db, package, require_approval=args.require_approval)
    if not result["ok"]:
        print(f"error: {result['error']}", file=sys.stderr)
        return 1
    print(f"imported '{result['playbook_id']}' ({result['versions_imported']} version(s)), status: {result['status']}")
    return 0


def cmd_playbook_seed(args: argparse.Namespace) -> int:
    """Seed built-in YAML playbooks into the DB."""
    from kali_mcp.studio.playbook_service import seed_builtin_playbooks

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    count = seed_builtin_playbooks(db)
    print(f"seeded {count} built-in playbook(s)")
    return 0


# ── Tool registry commands ───────────────────────────────────────────────


def cmd_tool_list(args: argparse.Namespace) -> int:
    """List tool definitions."""
    from kali_mcp.studio.service_tools import list_tool_definitions

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    rows = list_tool_definitions(
        db, provider=args.provider, visibility=args.visibility, enabled=args.enabled
    )
    table = [
        [r.get("tool_id", ""), r.get("name", "")[:40], r.get("provider", ""), r.get("visibility", ""), str(r.get("enabled", 0))]
        for r in rows
    ]
    _print_table(table, ["tool_id", "name", "provider", "visibility", "enabled"])
    return 0


def cmd_tool_visibility(args: argparse.Namespace) -> int:
    """Set tool visibility."""
    from kali_mcp.studio.service_tools import set_tool_visibility

    valid = {"agent_callable", "playbook_selectable", "internal", "hidden"}
    if args.visibility not in valid:
        print(f"invalid visibility '{args.visibility}' — use: {', '.join(sorted(valid))}", file=sys.stderr)
        return 1
    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    ok = set_tool_visibility(db, args.id, args.visibility)
    if not ok:
        print(f"tool '{args.id}' not found", file=sys.stderr)
        return 1
    print(f"tool '{args.id}' visibility set to '{args.visibility}'")
    return 0


# ── Execution commands ───────────────────────────────────────────────────


def cmd_execution_list(args: argparse.Namespace) -> int:
    """List workflow executions."""
    from kali_mcp.studio.service_executions import list_executions

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    rows = list_executions(db, status=args.status, playbook_id=args.playbook_id, limit=args.limit, offset=args.offset)
    table = [
        [r.get("execution_id", ""), r.get("playbook_id", ""), r.get("status", ""), r.get("started_at") or "-", r.get("completed_at") or "-"]
        for r in rows
    ]
    _print_table(table, ["execution_id", "playbook_id", "status", "started_at", "completed_at"])
    return 0


def cmd_execution_cancel(args: argparse.Namespace) -> int:
    """Cancel a running execution."""
    from kali_mcp.studio.service_executions import cancel_execution

    db = _get_db()
    if db is None:
        print("database unavailable", file=sys.stderr)
        return 1
    ok = cancel_execution(db, args.id)
    if not ok:
        print(f"execution '{args.id}' not found or not running", file=sys.stderr)
        return 1
    print(f"execution '{args.id}' cancelled")
    return 0


# ── parser ───────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kmcp",
        description="Kali MCP Server CLI — server, monitor, data purge, and Playbook Studio management.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start / s
    p_start = sub.add_parser("start", aliases=["s"], help="Start the MCP server")
    p_start.add_argument("--host", default=None, help="Listen address (default: MCP_HOST or 0.0.0.0)")
    p_start.add_argument("--port", default=None, help="Listen port (default: MCP_PORT or 8399)")
    p_start.set_defaults(func=cmd_start)

    # monitor / m
    p_monitor = sub.add_parser("monitor", aliases=["m"], help="Launch the monitor TUI")
    p_monitor.add_argument("url", nargs="?", default=None, help="Base URL of the MCP server (default: http://127.0.0.1:8399)")
    p_monitor.set_defaults(func=cmd_monitor)

    # purge / p
    p_purge = sub.add_parser("purge", aliases=["p"], help="Purge stored data")
    p_purge.add_argument("scope", choices=["db", "vault", "all"], help="What to purge: db | vault | all")
    p_purge.add_argument("--confirm", "-y", action="store_true", help="Skip confirmation prompt")
    p_purge.set_defaults(func=cmd_purge)

    # ── playbook ─────────────────────────────────────────────────
    p_pb = sub.add_parser("playbook", help="Playbook Studio management")
    pb_sub = p_pb.add_subparsers(dest="subcommand", required=True)

    pb_list = pb_sub.add_parser("list", help="List playbooks")
    pb_list.add_argument("--status", default=None, help="Filter by status")
    pb_list.set_defaults(func=cmd_playbook_list)

    pb_create = pb_sub.add_parser("create", help="Create a draft playbook")
    pb_create.add_argument("--id", required=True, help="Playbook ID")
    pb_create.add_argument("--name", required=True, help="Playbook name")
    pb_create.add_argument("--description", default=None, help="Description")
    pb_create.add_argument("--category", default=None, help="Category")
    pb_create.add_argument("--author", default=None, help="Author")
    pb_create.set_defaults(func=cmd_playbook_create)

    pb_show = pb_sub.add_parser("show", help="Show playbook metadata + latest definition")
    pb_show.add_argument("id", help="Playbook ID")
    pb_show.set_defaults(func=cmd_playbook_show)

    pb_validate = pb_sub.add_parser("validate", help="Validate a playbook definition")
    pb_validate.add_argument("id", help="Playbook ID")
    pb_validate.add_argument("--definition", default=None, help="JSON string or file path")
    pb_validate.add_argument("--for-publish", action="store_true", help="Apply stricter publish-time rules")
    pb_validate.set_defaults(func=cmd_playbook_validate)

    pb_preview = pb_sub.add_parser("preview", help="Dry-run a playbook (no execution)")
    pb_preview.add_argument("id", help="Playbook ID")
    pb_preview.add_argument("--definition", default=None, help="JSON string or file path")
    pb_preview.set_defaults(func=cmd_playbook_preview)

    pb_test = pb_sub.add_parser("test", help="Controlled test execution (mocked tools)")
    pb_test.add_argument("id", help="Playbook ID")
    pb_test.add_argument("--definition", default=None, help="JSON string or file path")
    pb_test.set_defaults(func=cmd_playbook_test)

    pb_publish = pb_sub.add_parser("publish", help="Publish an immutable playbook version")
    pb_publish.add_argument("id", help="Playbook ID")
    pb_publish.add_argument("--version", required=True, help="Version string")
    pb_publish.add_argument("--definition", default=None, help="JSON string or file path")
    pb_publish.add_argument("--notes", default=None, help="Publish notes")
    pb_publish.set_defaults(func=cmd_playbook_publish)

    pb_versions = pb_sub.add_parser("versions", help="List version history")
    pb_versions.add_argument("id", help="Playbook ID")
    pb_versions.set_defaults(func=cmd_playbook_versions)

    pb_rollback = pb_sub.add_parser("rollback", help="Roll back to an earlier published version")
    pb_rollback.add_argument("id", help="Playbook ID")
    pb_rollback.add_argument("--version-id", required=True, help="Version ID to roll back to")
    pb_rollback.set_defaults(func=cmd_playbook_rollback)

    pb_export = pb_sub.add_parser("export", help="Export a playbook package")
    pb_export.add_argument("id", help="Playbook ID")
    pb_export.add_argument("--out", default=None, help="Output file path (default: print to stdout)")
    pb_export.set_defaults(func=cmd_playbook_export)

    pb_import = pb_sub.add_parser("import", help="Import a playbook package")
    pb_import.add_argument("file", help="Package JSON file path")
    pb_import.add_argument("--require-approval", action="store_true", default=True, help="Require approval before activation (default: true)")
    pb_import.add_argument("--no-require-approval", dest="require_approval", action="store_false", help="Activate without approval")
    pb_import.set_defaults(func=cmd_playbook_import)

    pb_seed = pb_sub.add_parser("seed", help="Seed built-in YAML playbooks into the DB")
    pb_seed.set_defaults(func=cmd_playbook_seed)

    # ── tool ─────────────────────────────────────────────────────
    p_tool = sub.add_parser("tool", help="Tool registry management")
    tool_sub = p_tool.add_subparsers(dest="subcommand", required=True)

    t_list = tool_sub.add_parser("list", help="List tool definitions")
    t_list.add_argument("--provider", default=None, help="Filter by provider")
    t_list.add_argument("--visibility", default=None, help="Filter by visibility")
    t_list.add_argument("--enabled", default=None, help="Filter by enabled (true/false)")
    t_list.set_defaults(func=cmd_tool_list)

    t_vis = tool_sub.add_parser("visibility", help="Set tool visibility")
    t_vis.add_argument("id", help="Tool ID")
    t_vis.add_argument("visibility", help="Visibility mode: agent_callable | playbook_selectable | internal | hidden")
    t_vis.set_defaults(func=cmd_tool_visibility)

    # ── execution ────────────────────────────────────────────────
    p_exec = sub.add_parser("execution", help="Execution monitoring")
    exec_sub = p_exec.add_subparsers(dest="subcommand", required=True)

    e_list = exec_sub.add_parser("list", help="List executions")
    e_list.add_argument("--status", default=None, help="Filter by status")
    e_list.add_argument("--playbook-id", default=None, help="Filter by playbook ID")
    e_list.add_argument("--limit", type=int, default=50, help="Max rows (default: 50)")
    e_list.add_argument("--offset", type=int, default=0, help="Offset (default: 0)")
    e_list.set_defaults(func=cmd_execution_list)

    e_cancel = exec_sub.add_parser("cancel", help="Cancel a running execution")
    e_cancel.add_argument("id", help="Execution ID")
    e_cancel.set_defaults(func=cmd_execution_cancel)

    # ── frontend / studio (open in browser) ───────────────────────
    _frontend_commands = [
        ("studio", ["st"], "Open the Playbook Studio UI in a browser (starts the server if needed)"),
        ("frontend", ["fe", "front-end"], "Open the Playbook Studio frontend in the browser"),
        ("web", ["w"], "Open the Playbook Studio frontend in the browser"),
        ("ui", [], "Open the Playbook Studio frontend in the browser"),
        ("browser", [], "Open the Playbook Studio frontend in the browser"),
        ("open", [], "Open the Playbook Studio frontend in the browser"),
        ("gui", [], "Open the Playbook Studio frontend in the browser"),
        ("dashboard", ["dash"], "Open the Playbook Studio frontend in the browser"),
        ("webui", ["web-ui", "web_ui"], "Open the Playbook Studio frontend in the browser"),
        ("open-frontend", ["open_frontend", "openfrontend"], "Open the Playbook Studio frontend in the browser"),
        ("start-frontend", ["start_frontend", "startfrontend"], "Open the Playbook Studio frontend in the browser"),
        ("frontend-browser", ["frontend_browser", "frontendbrowser"], "Open the Playbook Studio frontend in the browser"),
    ]
    for _name, _aliases, _help in _frontend_commands:
        _norm = _name.replace("-", "_")
        _func = globals().get(f"cmd_{_norm}", cmd_frontend)
        _p = sub.add_parser(_name, aliases=_aliases, help=_help)
        _p.add_argument("url", nargs="?", default=None, help="Base URL of the MCP server or frontend URL")
        _p.add_argument("--url", dest="url", default=None, help="Base URL of the MCP server or frontend URL")
        _p.add_argument("--host", default=None, help="Listen host (default: MCP_HOST or 127.0.0.1)")
        _p.add_argument("--port", default=None, help="Listen port (default: MCP_PORT or 8399)")
        _p.add_argument("--no-browser", "--no-open", dest="no_browser", action="store_true", help="Do not open the browser")
        _p.set_defaults(func=_func)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    if not argv:
        # No command given: print help and exit (like git/docker/kubectl),
        # instead of silently starting the server.
        parser.print_help(sys.stdout)
        return 0
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())