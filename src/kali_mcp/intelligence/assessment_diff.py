"""Assessment Diff Engine — compare two assessment runs.

Detects new findings, resolved findings, changed severity, changed confidence,
new assets, and new services between two assessments identified by
assessment_id (or job_id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiffResult:
    """Result of comparing two assessments."""

    assessment_id_a: str
    assessment_id_b: str
    new_findings: list[dict[str, Any]] = field(default_factory=list)
    resolved_findings: list[dict[str, Any]] = field(default_factory=list)
    changed_findings: list[dict[str, Any]] = field(default_factory=list)
    new_assets: list[dict[str, Any]] = field(default_factory=list)
    resolved_assets: list[dict[str, Any]] = field(default_factory=list)
    new_services: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id_a": self.assessment_id_a,
            "assessment_id_b": self.assessment_id_b,
            "new_findings": self.new_findings,
            "resolved_findings": self.resolved_findings,
            "changed_findings": self.changed_findings,
            "new_assets": self.new_assets,
            "resolved_assets": self.resolved_assets,
            "new_services": self.new_services,
            "summary": self.summary,
        }


class AssessmentDiffer:
    """Compares two assessment runs and surfaces what changed."""

    def __init__(self, db_manager: Any | None = None) -> None:
        self._db = db_manager

    # ── public API ────────────────────────────────────────────────────

    def diff(self, assessment_id_a: str, assessment_id_b: str) -> DiffResult:
        """Compare assessment A (baseline) with assessment B (current).

        Args:
            assessment_id_a: Baseline assessment identifier.
            assessment_id_b: Current assessment identifier.

        Returns:
            A :class:`DiffResult` describing the differences.
        """
        findings_a = self._get_findings(assessment_id_a)
        findings_b = self._get_findings(assessment_id_b)
        assets_a = self._get_assets(assessment_id_a)
        assets_b = self._get_assets(assessment_id_b)
        services_a = self._get_services(assessment_id_a)
        services_b = self._get_services(assessment_id_b)

        # Index findings by (asset_id, title) for comparison
        idx_a = self._index_findings(findings_a)
        idx_b = self._index_findings(findings_b)

        keys_a = set(idx_a.keys())
        keys_b = set(idx_b.keys())

        new_keys = keys_b - keys_a
        resolved_keys = keys_a - keys_b
        common_keys = keys_a & keys_b

        new_findings = [idx_b[k] for k in sorted(new_keys)]
        resolved_findings = [idx_a[k] for k in sorted(resolved_keys)]

        # Changed findings: same key but different severity or confidence
        changed_findings: list[dict[str, Any]] = []
        for k in sorted(common_keys):
            fa = idx_a[k]
            fb = idx_b[k]
            changes: dict[str, Any] = {}
            if fa.get("severity") != fb.get("severity"):
                changes["severity"] = {"from": fa.get("severity"), "to": fb.get("severity")}
            if fa.get("confidence") != fb.get("confidence"):
                changes["confidence"] = {"from": fa.get("confidence"), "to": fb.get("confidence")}
            if fa.get("validation_status") != fb.get("validation_status"):
                changes["validation_status"] = {
                    "from": fa.get("validation_status"),
                    "to": fb.get("validation_status"),
                }
            if changes:
                changed_findings.append(
                    {
                        "finding_id": fb.get("id"),
                        "title": fb.get("title"),
                        "asset_id": fb.get("asset_id"),
                        "changes": changes,
                        "current": fb,
                        "previous": fa,
                    }
                )

        # Assets
        ids_a = {a.get("asset_id") for a in assets_a}
        ids_b = {a.get("asset_id") for a in assets_b}
        new_assets = [a for a in assets_b if a.get("asset_id") not in ids_a]
        resolved_assets = [a for a in assets_a if a.get("asset_id") not in ids_b]

        # Services
        svc_keys_a = {self._service_key(s) for s in services_a}
        {self._service_key(s) for s in services_b}
        new_services = [s for s in services_b if self._service_key(s) not in svc_keys_a]

        summary = {
            "findings_a": len(findings_a),
            "findings_b": len(findings_b),
            "new_findings_count": len(new_findings),
            "resolved_findings_count": len(resolved_findings),
            "changed_findings_count": len(changed_findings),
            "assets_a": len(assets_a),
            "assets_b": len(assets_b),
            "new_assets_count": len(new_assets),
            "resolved_assets_count": len(resolved_assets),
            "new_services_count": len(new_services),
        }

        return DiffResult(
            assessment_id_a=assessment_id_a,
            assessment_id_b=assessment_id_b,
            new_findings=new_findings,
            resolved_findings=resolved_findings,
            changed_findings=changed_findings,
            new_assets=new_assets,
            resolved_assets=resolved_assets,
            new_services=new_services,
            summary=summary,
        )

    # ── internal helpers ─────────────────────────────────────────────

    def _get_findings(self, assessment_id: str) -> list[dict[str, Any]]:
        if self._db is not None:
            try:
                result = self._db.get_findings_by_assessment(assessment_id)
                if isinstance(result, dict):
                    return result.get("findings", [])
                return result if isinstance(result, list) else []
            except Exception:
                pass
        return []

    def _get_assets(self, assessment_id: str) -> list[dict[str, Any]]:
        if self._db is not None:
            try:
                # Query assets via target linkage through scans
                result = self._db.conn.execute(
                    """
                    SELECT DISTINCT a.* FROM assets a
                    JOIN scans s ON a.target_id = s.id OR a.asset_id = s.assessment_id
                    WHERE s.assessment_id = ?
                    """,
                    (assessment_id,),
                ).fetchall()
                return [dict(r) for r in result]
            except Exception:
                pass
        return []

    def _get_services(self, assessment_id: str) -> list[dict[str, Any]]:
        if self._db is not None:
            try:
                result = self._db.conn.execute(
                    """
                    SELECT DISTINCT s.* FROM services s
                    JOIN assets a ON s.asset_id = a.id
                    JOIN scans sc ON a.target_id = sc.id OR a.asset_id = sc.assessment_id
                    WHERE sc.assessment_id = ?
                    """,
                    (assessment_id,),
                ).fetchall()
                return [dict(r) for r in result]
            except Exception:
                pass
        return []

    @staticmethod
    def _index_findings(findings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Index findings by (asset_id, title) key."""
        idx: dict[str, dict[str, Any]] = {}
        for f in findings:
            key = f"{f.get('asset_id', 'unknown')}|{f.get('title', 'unknown')}"
            idx[key] = f
        return idx

    @staticmethod
    def _service_key(service: dict[str, Any]) -> str:
        return (
            f"{service.get('asset_id', '')}:{service.get('port', '')}/{service.get('protocol', '')}"
        )
