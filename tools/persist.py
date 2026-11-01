"""Shared persistence helpers: SQLite + vault deposits for tool wrappers.

Every tool run is recorded as a `scans` row and a generic `findings` row.
Tools that parse structured results (ports, paths, credentials, hashes) pass
them in as `findings` / `credentials` lists for per-item storage.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from utils.vault import vault_write

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_fs(name: str) -> str:
    return _SAFE_NAME.sub("_", name).strip("_") or "unknown"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def extract_target(arguments: dict[str, Any]) -> str:
    """Best-effort extraction of a target identifier from tool arguments."""
    for key in ("target", "domain", "host", "repo", "query"):
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "unknown"


def persist_run(
    tool_name: str,
    arguments: dict[str, Any],
    command: str | list[str],
    result: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
    credentials: list[dict[str, Any]] | None = None,
    target_type: str = "host",
) -> dict[str, Any]:
    """Record a tool run in SQLite and deposit its output in the vault.

    `result` is the parsed ExecutionResult dict (stdout/stderr/exit_code/...).
    `findings` items may carry: type, severity, title, description, evidence,
    port, service, url.  `credentials` items carry: service, username,
    password, hash.

    All failures are swallowed — persistence must never break tool execution.
    Returns a small summary dict for inclusion in tool responses.
    """
    summary: dict[str, Any] = {"db_recorded": False, "vault_deposited": False}
    try:
        from db import manager as dbm

        target = extract_target(arguments)
        command_str = command if isinstance(command, str) else " ".join(command)

        data: dict[str, Any] | None = None
        if isinstance(result, dict) and "stdout" in result:
            data = result

        # ── SQLite ────────────────────────────────────────────────────────
        try:
            db = dbm.get_db()
            if db is not None:
                target_id = db.upsert_target(target, target_type=target_type)
                scan_id = db.add_scan(
                    target_id,
                    tool_name,
                    command_str,
                    (data or {}).get("start_time") or now_iso(),
                    (data or {}).get("end_time") or now_iso(),
                    (data or {}).get("duration") or 0.0,
                    1 if (data or {}).get("success") else 0,
                    len(findings or []),
                    None,
                )
                if data:
                    evidence = (
                        (data.get("stdout") or "") + "\n" + (data.get("stderr") or "")
                    )[:100_000]
                    db.add_finding(
                        target_id,
                        scan_id,
                        tool_name,
                        "execution",
                        "informational",
                        f"{tool_name} execution",
                        evidence,
                        evidence,
                    )
                for f in findings or []:
                    db.add_finding(
                        target_id,
                        scan_id,
                        tool_name,
                        f.get("type", "note"),
                        f.get("severity", "informational"),
                        f.get("title", "finding"),
                        f.get("description", ""),
                        f.get("evidence", ""),
                        port=f.get("port"),
                        service=f.get("service"),
                        url=f.get("url"),
                    )
                for c in credentials or []:
                    db.add_credential(
                        target_id,
                        c.get("service", "unknown"),
                        c.get("username", ""),
                        password=c.get("password"),
                        hash_value=c.get("hash"),
                        source_tool=tool_name,
                    )
                summary["db_recorded"] = True
                summary["target_id"] = target_id
                summary["scan_id"] = scan_id
        except Exception:
            pass

        # ── Vault ─────────────────────────────────────────────────────────
        try:
            target = extract_target(arguments)
            payload = {
                "tool": tool_name,
                "target": target,
                "command": command_str,
                "recorded_at": now_iso(),
                "result": data,
                "findings": findings or [],
                "credentials": credentials or [],
            }
            vault_write(
                f"findings/{_sanitize_fs(target)}",
                f"{now_iso().replace(':', '')}_{tool_name}",
                payload,
            )
            for c in credentials or []:
                vault_write(
                    "credentials",
                    f"{_sanitize_fs(c.get('service', 'svc'))}_{_sanitize_fs(c.get('username', 'user'))}_{now_iso().replace(':', '')}",
                    {**c, "source_tool": tool_name, "target": target},
                )
            summary["vault_deposited"] = True
        except Exception:
            pass
    except Exception:
        pass
    return summary


# ── Per-tool output parsers ────────────────────────────────────────────────────

_HYDRA_RE = re.compile(
    r"\[(\d+)\]\[(\w[\w-]*)\]\s+host:\s*(\S+)\s+login:\s*(\S+)\s+password:\s*(\S+)"
)
_MEDUSA_RE = re.compile(
    r"\[([\w-]+)\]\s+host:\s*(\S+)\s+user:\s*(\S+)\s+password:\s*(\S+?):?\s+SUCCESS",
    re.IGNORECASE,
)
_JOBN_SHOW_RE = re.compile(r"^([^:\s]+):([^\s:]+)$")  # hash:pass (john --show)
_JOBN_PAREN_RE = re.compile(r"^(.+?)\s+\(([^)]+)\)$")  # password (user)
_GOBBUSTER_RE = re.compile(
    r"((?:https?://\S+|/\S+?))\s+\(Status:\s*(\d+)\)", re.IGNORECASE
)
_DIRB_RE = re.compile(r"^\+?\s*(https?://\S+?)\s*\(CODE:(\d+)\)", re.IGNORECASE)
_MASSCAN_RE = re.compile(
    r"Discovered open port\s+(\d+)/(tcp|udp)\s+on\s+([\d.]+)", re.IGNORECASE
)


def parse_hydra(stdout: str) -> list[dict[str, Any]]:
    """Extract valid credential pairs from hydra output."""
    creds = []
    for m in _HYDRA_RE.finditer(stdout or ""):
        port, service, host, login, password = m.groups()
        creds.append(
            {
                "service": service,
                "username": login,
                "password": password,
                "host": host,
                "port": int(port) if port.isdigit() else None,
            }
        )
    return creds


def parse_medusa(stdout: str) -> list[dict[str, Any]]:
    creds = []
    for m in _MEDUSA_RE.finditer(stdout or ""):
        service, host, user, password = m.groups()
        creds.append(
            {
                "service": service,
                "username": user,
                "password": password,
                "host": host,
            }
        )
    return creds


def parse_john(stdout: str) -> list[dict[str, Any]]:
    """Extract cracked passwords from john output ('hash:password' or 'password (user)')."""
    creds = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line or len(line) > 300:
            continue
        if ":" in line and line.count(":") == 1:
            h, pw = line.split(":", 1)
            if h and pw:
                creds.append(
                    {"service": "hash", "username": "", "hash": h, "password": pw}
                )
                continue
        m = _JOBN_PAREN_RE.match(line)
        if m:
            creds.append(
                {"service": "hash", "username": m.group(2), "password": m.group(1)}
            )
    return creds


def parse_hashcat(stdout: str) -> list[dict[str, Any]]:
    """Extract cracked hash:password pairs from hashcat --show style output."""
    creds = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if ":" in line and not line.startswith(("Hash.Mode", "Options")):
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1] and len(parts[0]) >= 8:
                creds.append(
                    {"service": "hash", "username": parts[0], "password": parts[1]}
                )
    return creds


def parse_gobuster(stdout: str) -> list[dict[str, Any]]:
    """Parse gobuster dir output — full URLs or relative paths with status codes."""
    findings = []
    for m in _GOBBUSTER_RE.finditer(stdout or ""):
        path, status = m.groups()
        findings.append(
            {
                "type": "web_path",
                "severity": "informational",
                "title": f"Path found: {path}",
                "description": f"HTTP {status}",
                "evidence": path,
                "url": path,
            }
        )
    return findings


def parse_dirb(stdout: str) -> list[dict[str, Any]]:
    findings = []
    for m in _DIRB_RE.finditer(stdout or ""):
        url, code = m.groups()
        kind = "web_dir" if url.endswith("/") else "web_path"
        findings.append(
            {
                "type": kind,
                "severity": "informational",
                "title": f"{kind}: {url}",
                "description": f"HTTP {code}",
                "evidence": url,
                "url": url,
            }
        )
    return findings


def parse_wfuzz(stdout: str) -> list[dict[str, Any]]:
    """Parse wfuzz results table lines: ID, Response, Lines, Word, Chars, URL."""
    findings = []
    for line in (stdout or "").splitlines():
        parts = line.strip().split()
        if len(parts) < 6:
            continue
        ident = parts[0].rstrip(":")
        url = parts[-1].strip("'\"")
        if ident.isdigit() and parts[1].isdigit() and url.startswith("http"):
            findings.append(
                {
                    "type": "web_path",
                    "severity": "informational",
                    "title": f"wfuzz hit: {url}",
                    "description": f"code={parts[1]}",
                    "evidence": line.strip(),
                    "url": url,
                }
            )
    return findings


def parse_masscan(stdout: str) -> list[dict[str, Any]]:
    findings = []
    for m in _MASSCAN_RE.finditer(stdout or ""):
        port, proto, host = m.groups()
        findings.append(
            {
                "type": "open_port",
                "severity": "informational",
                "title": f"Open port {port}/{proto} on {host}",
                "description": "Discovered by masscan",
                "evidence": m.group(0),
                "port": int(port),
                "service": proto,
            }
        )
    return findings


def parse_responder_hashes(stdout: str) -> list[dict[str, Any]]:
    """Extract captured hash events from responder output."""
    findings = []
    for line in (stdout or "").splitlines():
        if "NTLMv" in line or ("Hash" in line and ("[" in line or ":" in line)):
            findings.append(
                {
                    "type": "captured_hash",
                    "severity": "high",
                    "title": "Captured authentication hash",
                    "description": line.strip()[:200],
                    "evidence": line.strip(),
                }
            )
    return findings


# ── Shared execution + persistence runner ─────────────────────────────────────


async def run_tool_with_persistence(
    tool: Any,
    arguments: dict[str, Any],
    parser: Any = None,
    target_type: str = "host",
) -> dict[str, Any]:
    """Run a tool's command through the engine, parse, persist, and wrap output.

    The stdout of the returned MCP response is replaced with a JSON contract:
      {raw, normalized, parsed_at, parse_success, persistence}.

    `parser` is an optional callable(stdout) -> (findings, credentials).
    """
    from execution import engine
    from models import ToolError
    from responses import error_response

    try:
        tool.validate(arguments)
    except ValueError as e:
        return error_response(ToolError(error="Validation error", details=str(e)))

    cmd = tool.build_command(arguments)
    timeout = arguments.get("timeout", tool.default_timeout)
    result = await engine.execute(command=cmd, tool=tool.name, timeout=timeout)
    data = result.to_dict()

    findings: list[dict[str, Any]] = []
    credentials: list[dict[str, Any]] = []
    parse_success = False
    normalized: dict[str, Any] = {}
    if parser is not None:
        try:
            findings, credentials = parser(result.stdout or "")
            parse_success = True
        except Exception:  # noqa: BLE001 — parsing must not fail the run
            findings, credentials = [], []
    if hasattr(tool, "normalize"):
        try:
            norm = tool.normalize(
                result.stdout or "", result.stderr or "", result.exit_code
            )
            normalized = norm.get("normalized", {}) if isinstance(norm, dict) else {}
        except Exception:  # noqa: BLE001
            normalized = {}

    summary = persist_run(
        tool.name,
        arguments,
        cmd,
        data,
        findings=findings,
        credentials=credentials,
        target_type=target_type,
    )

    payload = {
        "raw": data,
        "normalized": normalized,
        "parsed_at": now_iso(),
        "parse_success": parse_success,
        "persistence": summary,
        "findings": findings,
        "credentials": credentials,
    }
    data["stdout"] = json.dumps(payload, indent=2)
    return success_response_from_dict(data)


def success_response_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap an ExecutionResult dict into the MCP success response shape."""
    from responses import success_response

    class _Shim:
        def __init__(self, d: dict[str, Any]) -> None:
            self.__dict__.update(d)

        def to_dict(self) -> dict[str, Any]:
            return self.__dict__

    return success_response(_Shim(data))  # type: ignore[arg-type]


def wrap_execution_result(res: Any, name: str) -> dict[str, Any]:
    """Attach the standard payload contract to an ExecutionResult and wrap it."""
    payload = {
        "raw": res.to_dict(),
        "normalized": {"playbook": name},
        "parsed_at": now_iso(),
        "parse_success": True,
    }
    res.stdout = json.dumps(payload, indent=2)
    from responses import success_response

    return success_response(res)
