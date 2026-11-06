"""``intelligence.*`` internal modules for Playbook Studio.

Pure-Python operations: finding correlation and enrichment.
No external binaries are invoked.
"""

from __future__ import annotations

from typing import Any

from kali_mcp.workflow import modules_runtime as _mr


async def _correlate(
    ctx,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Correlate and deduplicate findings into a consolidated view."""
    if not isinstance(findings, list):
        return {"error": "findings must be a list", "correlated": [], "count": 0}

    seen: set[str] = set()
    correlated: list[dict[str, Any]] = []
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        dedup_key = finding.get("id") or finding.get("finding_id") or f"{finding.get('target','')}:{finding.get('type','')}:{finding.get('name','')}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        sev = str(finding.get("severity", "info")).lower()
        correlated.append(
            {
                "id": finding.get("id", finding.get("finding_id", "")),
                "target": finding.get("target", ""),
                "type": finding.get("type", ""),
                "name": finding.get("name", ""),
                "severity": sev,
                "severity_rank": severity_order.get(sev, 99),
                "evidence": finding.get("evidence", ""),
            }
        )

    correlated.sort(key=lambda f: f["severity_rank"])

    return {
        "correlated": correlated,
        "count": len(correlated),
        "unique_targets": len({f.get("target") for f in correlated if f.get("target")}),
    }


def register() -> None:
    """Register intelligence.* operations with the module runtime."""
    _mr.register(
        "intelligence.correlate",
        _correlate,
        input_schema={"type": "object", "required": ["findings"], "properties": {"findings": {"type": "array"}}},
        output_schema={
            "type": "object",
            "properties": {
                "correlated": {"type": "array"},
                "count": {"type": "integer"},
                "unique_targets": {"type": "integer"},
                "error": {"type": "string"},
            },
        },
    )


__all__ = ["_correlate", "register"]