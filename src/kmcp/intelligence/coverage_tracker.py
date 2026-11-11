"""Assessment Coverage Tracker — tracks what was tested vs what was missed.

Per assessment, records which assets/services were scanned by which tools,
what findings resulted, and where gaps remain (services never scanned,
assets with no findings).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


@dataclass
class CoverageRecord:
    """A single coverage record for an asset/service/tool combination."""

    asset_id: str
    service: str | None
    tool: str
    result_status: str  # scanned | no_findings | findings | error | skipped
    findings_count: int = 0
    timestamp: str = field(default_factory=_now_utc)


class CoverageTracker:
    """Tracks assessment coverage across assets, services, and tools."""

    def __init__(self) -> None:
        # assessment_id -> list[CoverageRecord]
        self._records: dict[str, list[CoverageRecord]] = {}
        # assessment_id -> set of asset_ids seen
        self._assets_seen: dict[str, set[str]] = {}
        # assessment_id -> set of (asset_id, service) tuples scanned
        self._services_scanned: dict[str, set[tuple[str, str | None]]] = {}
        # assessment_id -> set of tool names used
        self._tools_used: dict[str, set[str]] = {}
        # assessment_id -> total findings count
        self._findings_count: dict[str, int] = {}

    # ── public API ────────────────────────────────────────────────────

    def record_coverage(
        self,
        assessment_id: str,
        asset_id: str,
        service: str | None,
        tool: str,
        result_status: str,
        findings_count: int = 0,
    ) -> None:
        """Record that a tool scanned an asset/service.

        Args:
            assessment_id: The assessment this belongs to.
            asset_id: The asset scanned.
            service: The service scanned (or None for host-level scans).
            tool: The tool that ran.
            result_status: scanned | no_findings | findings | error | skipped.
            findings_count: Number of findings produced by this scan.
        """
        record = CoverageRecord(
            asset_id=asset_id,
            service=service,
            tool=tool,
            result_status=result_status,
            findings_count=findings_count,
        )
        self._records.setdefault(assessment_id, []).append(record)

        self._assets_seen.setdefault(assessment_id, set()).add(asset_id)
        self._services_scanned.setdefault(assessment_id, set()).add((asset_id, service))
        self._tools_used.setdefault(assessment_id, set()).add(tool)
        self._findings_count[assessment_id] = (
            self._findings_count.get(assessment_id, 0) + findings_count
        )

    def get_coverage_gaps(self, assessment_id: str) -> list[dict[str, Any]]:
        """Return coverage gaps for an assessment.

        Gaps include:
        - Assets discovered but never scanned (no coverage record).
        - Services discovered but never scanned.
        - Assets with coverage records but zero findings (potential gap).

        Args:
            assessment_id: The assessment to analyze.

        Returns:
            List of gap dicts with ``type``, ``asset_id``, ``service``, and
            ``description`` fields.
        """
        gaps: list[dict[str, Any]] = []
        assets_seen = self._assets_seen.get(assessment_id, set())
        services_scanned = self._services_scanned.get(assessment_id, set())
        records = self._records.get(assessment_id, [])

        # Build set of assets that have at least one scan record
        scanned_assets = {r.asset_id for r in records}

        # Assets discovered but never scanned
        for asset_id in assets_seen:
            if asset_id not in scanned_assets:
                gaps.append(
                    {
                        "type": "asset_unscanned",
                        "asset_id": asset_id,
                        "service": None,
                        "description": f"Asset {asset_id} was discovered but never scanned",
                    }
                )

        # Services discovered but never scanned
        for asset_id, service in services_scanned:
            if service is None:
                continue
            has_scan = any(r.asset_id == asset_id and r.service == service for r in records)
            if not has_scan:
                gaps.append(
                    {
                        "type": "service_unscanned",
                        "asset_id": asset_id,
                        "service": service,
                        "description": f"Service {service} on {asset_id} was discovered but never scanned",
                    }
                )

        # Assets with scans but zero findings (potential coverage gap)
        for asset_id in scanned_assets:
            asset_findings = sum(r.findings_count for r in records if r.asset_id == asset_id)
            if asset_findings == 0:
                gaps.append(
                    {
                        "type": "asset_no_findings",
                        "asset_id": asset_id,
                        "service": None,
                        "description": f"Asset {asset_id} was scanned but produced no findings",
                    }
                )

        return gaps

    def get_coverage_summary(self, assessment_id: str) -> dict[str, Any]:
        """Return a coverage summary for an assessment.

        Args:
            assessment_id: The assessment to summarize.

        Returns:
            Dict with percent covered, tools used, assets tested,
            services scanned, findings count, and gap count.
        """
        records = self._records.get(assessment_id, [])
        assets_seen = self._assets_seen.get(assessment_id, set())
        tools_used = self._tools_used.get(assessment_id, set())
        services_scanned = self._services_scanned.get(assessment_id, set())

        scanned_assets = {r.asset_id for r in records}
        total_assets = len(assets_seen)
        scanned_count = len(scanned_assets)

        total_findings = sum(r.findings_count for r in records)

        # Percent covered = assets scanned / assets seen
        percent_covered = (
            round((scanned_count / total_assets) * 100, 1) if total_assets > 0 else 0.0
        )

        return {
            "assessment_id": assessment_id,
            "percent_covered": percent_covered,
            "assets_discovered": total_assets,
            "assets_scanned": scanned_count,
            "services_scanned": len(services_scanned),
            "tools_used": sorted(tools_used),
            "tools_count": len(tools_used),
            "total_findings": total_findings,
            "gap_count": len(self.get_coverage_gaps(assessment_id)),
        }

    def get_records(self, assessment_id: str) -> list[dict[str, Any]]:
        """Return all coverage records for an assessment as dicts."""
        return [
            {
                "asset_id": r.asset_id,
                "service": r.service,
                "tool": r.tool,
                "result_status": r.result_status,
                "findings_count": r.findings_count,
                "timestamp": r.timestamp,
            }
            for r in self._records.get(assessment_id, [])
        ]
