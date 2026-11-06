"""Result aggregation and normalization for playbook output."""

from __future__ import annotations

from typing import Any


def aggregate_module_results(
    module_results: dict[str, Any],
) -> dict[str, Any]:
    """Combine all module outputs into a clean, de-duplicated structure."""
    aggregated: dict[str, Any] = {
        "dns": {},
        "ip_intelligence": {},
        "tls": {},
        "network": {},
        "web": {},
        "findings": [],
        "assets": [],
        "evidence": [],
    }

    for mod_id, result in module_results.items():
        if not isinstance(result, dict):
            continue
        if mod_id.startswith("dns"):
            aggregated["dns"].update(result)
        elif mod_id.startswith("ip"):
            aggregated["ip_intelligence"].update(result)
        elif mod_id.startswith("tls"):
            aggregated["tls"].update(result)
        elif mod_id.startswith("network"):
            aggregated["network"].update(result)
        elif mod_id.startswith("web"):
            aggregated["web"].update(result)

        aggregated["findings"].extend(result.get("findings", []))
        aggregated["assets"].extend(result.get("assets", []))
        aggregated["evidence"].extend(result.get("evidence", []))

    return aggregated


def deduplicate_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate findings by title + asset."""
    seen: dict[str, dict[str, Any]] = {}
    for f in findings:
        key = f"{f.get('asset_id', 'unknown')}|{f.get('title', 'unknown')}"
        if key in seen:
            existing = seen[key]
            existing["source_modules"] = list(
                set(existing.get("source_modules", []) + f.get("source_modules", []))
            )
            existing["evidence_refs"] = list(
                set(existing.get("evidence_refs", []) + f.get("evidence_refs", []))
            )
            existing["confidence"] = min(0.99, existing.get("confidence", 0.5) + 0.1)
        else:
            seen[key] = dict(f)
    return list(seen.values())
