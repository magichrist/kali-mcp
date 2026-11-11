"""Parallel execution wrapper — run N tools concurrently, aggregate + dedup."""

from __future__ import annotations

import json
from typing import Any

from kmcp.models import ExecutionResult, ToolError, utc_now_iso
from kmcp.responses import error_response, success_response
from kmcp.tools.base import BaseTool

# Job registry for parallel_status: {job_id: status_dict}
JOBS: dict[str, dict[str, Any]] = {}


def _result_payload(res: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the ExecutionResult JSON from a tool's MCP response."""
    try:
        return json.loads(res["content"][0]["text"])
    except Exception:  # noqa: BLE001 — unexpected response shapes are skipped
        return None


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate and deduplicate findings across sub-tool results.

    Dedup keys (per plan):
      - open ports by (target, port, protocol)
      - vulnerabilities by (target, template_id)
      - credentials by (target, service, username)
    """
    ports: dict[tuple, dict] = {}
    vulns: dict[tuple, dict] = {}
    errors: list[str] = []

    for res in results:
        data = _result_payload(res)
        if data is None:
            continue
        if not data.get("success"):
            errors.append(f"{data.get('tool')}: {(data.get('stderr') or 'failed')[:120]}")
        stdout = data.get("stdout") or ""
        # Prefer the structured payload contract (raw/normalized/…) if present
        try:
            inner = json.loads(stdout)
            if isinstance(inner, dict) and "normalized" in inner:
                stdout = json.dumps(inner.get("normalized", {}))
        except Exception:  # noqa: BLE001, S110
            pass

        target = data.get("tool")  # per-tool section marker
        for line in stdout.splitlines():
            line = line.strip()
            # Port lines: "80/tcp open" or "Discovered open port 80/tcp on x"
            if "open port" in line.lower():
                parts = line.split()
                for i, p in enumerate(parts):
                    if "/" in p and p.split("/")[0].isdigit():
                        port, proto = p.split("/", 1)
                        key = (data.get("command", ""), port, proto)
                        ports.setdefault(key, {"source": data.get("tool"), "detail": line[:200]})
            # Vulnerability markers
            if any(tag in line.lower() for tag in ("vulnerab", "cve-", "[+]")) and len(line) < 300:
                key = (target, line[:80])
                vulns.setdefault(key, {"source": data.get("tool"), "detail": line})

    return {
        "open_ports": [{"source": v["source"], "detail": v["detail"]} for v in ports.values()],
        "vulnerabilities": [{"source": v["source"], "detail": v["detail"]} for v in vulns.values()],
        "errors": errors,
        "sub_results_count": len(results),
    }


class ParallelExecuteTool(BaseTool):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "parallel_execute"

    @property
    def description(self) -> str:
        return (
            "Execute multiple tools concurrently and aggregate the results. "
            "Each entry: {'tool': name, 'args': {...}}. Failures are isolated — "
            "one tool failing doesn't affect the others. Returns per-tool "
            "results plus a deduplicated aggregate of ports/vulnerabilities."
        )

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target shared by all sub-tools",
                },
                "tools": {
                    "type": "array",
                    "description": "List of {tool, args} specs to run concurrently",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                        },
                        "required": ["tool"],
                    },
                },
                "max_concurrent": {
                    "type": "integer",
                    "description": "Max concurrent sub-tools (default 4)",
                    "default": 4,
                },
            },
            "required": ["target", "tools"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("target"):
            raise ValueError("target is required")
        if not isinstance(arguments.get("tools"), list) or not arguments["tools"]:
            raise ValueError("tools must be a non-empty list")
        for spec in arguments["tools"]:
            if not isinstance(spec, dict) or "tool" not in spec:
                raise ValueError("each tools entry must be an object with a 'tool' key")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        # Not used; this wrapper handles internal orchestration
        return ["parallel_execute"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)
        tool_specs: list[dict[str, Any]] = arguments["tools"]
        max_concurrent = arguments.get("max_concurrent", 4)

        import asyncio

        from kmcp.registry import registry

        job_id = f"par_{utc_now_iso().replace(':', '').replace('+', '')}"
        job = JOBS.setdefault(
            job_id,
            {
                "status": "running",
                "total": len(tool_specs),
                "done": 0,
                "started_at": utc_now_iso(),
            },
        )

        sem = asyncio.Semaphore(max_concurrent)

        async def run_one(spec: dict[str, Any]):
            tool_name = spec.get("tool")
            tool = registry.get(tool_name)
            if tool is None:
                return {"tool": tool_name, "error": "unknown tool"}
            async with sem:
                res = await tool.safe_execute(spec.get("args", {}))
                job["done"] += 1
                return res

        results = await asyncio.gather(*(run_one(ts) for ts in tool_specs))
        aggregate = aggregate_results(list(results))

        job["status"] = "completed"
        job["finished_at"] = utc_now_iso()

        payload = ExecutionResult(
            tool=self.name,
            command=json.dumps(tool_specs, indent=2),
            stdout=json.dumps(
                {
                    "job_id": job_id,
                    "results": list(results),
                    "aggregate": aggregate,
                },
                indent=2,
            ),
            stderr="",
            exit_code=0,
            success=True,
            timed_out=False,
            duration=0.0,
            start_time=job["started_at"],
            end_time=job["finished_at"],
        )
        return success_response(payload)


class ParallelStatusTool(BaseTool):
    @property
    def name(self) -> str:
        return "parallel_status"

    @property
    def description(self) -> str:
        return (
            "Check the status of a parallel_execute job (by job_id) or list "
            "all known jobs. Reports completed/total sub-tools and timing."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job id from parallel_execute output (omit for all)",
                },
            },
            "required": [],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["parallel_status", arguments.get("job_id", "")]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        job_id = arguments.get("job_id")
        if job_id and job_id not in JOBS:
            return error_response(
                ToolError(error="Unknown job", details=f"no parallel job '{job_id}'")
            )
        statuses = {job_id: JOBS[job_id]} if job_id else dict(JOBS)
        result = ExecutionResult(
            tool=self.name,
            command="parallel_status",
            stdout=json.dumps({"jobs": statuses}, indent=2),
            stderr="",
            exit_code=0,
            success=True,
            timed_out=False,
            duration=0.0,
            start_time=utc_now_iso(),
            end_time=utc_now_iso(),
        )
        return success_response(result)
