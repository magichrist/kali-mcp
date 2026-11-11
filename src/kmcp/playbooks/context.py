"""Assessment context — carries scope, state, and discovered assets through a playbook run.

The context is internal to the playbook engine and never exposed to agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


@dataclass
class Asset:
    """A discovered asset with type, provenance, and confidence."""

    asset_id: str
    asset_type: str  # domain | ip | subdomain | service | url | certificate
    name: str
    scope: str = "in-scope"
    discovered_by: str | None = None
    discovered_at: str = field(default_factory=_now_utc)
    confidence: float = 0.5
    attributes: dict[str, Any] = field(default_factory=dict)
    relationships: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Finding:
    """A normalized finding."""

    finding_id: str
    title: str
    severity: str  # critical | high | medium | low | informational
    confidence: float
    validation_status: str = "observed"
    asset_id: str | None = None
    source_modules: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    description: str = ""
    first_seen: str = field(default_factory=_now_utc)
    last_seen: str = field(default_factory=_now_utc)


@dataclass
class AssessmentContext:
    """Full state of an in-progress assessment."""

    assessment_id: str
    job_id: str
    playbook_id: str
    target: str
    scope_id: str
    profile: str  # safe_active | aggressive | passive
    detail: str  # summary | normal | full

    assets: dict[str, Asset] = field(default_factory=dict)
    findings: dict[str, Finding] = field(default_factory=dict)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    module_results: dict[str, Any] = field(default_factory=dict)
    execution_log: list[dict[str, Any]] = field(default_factory=list)

    def add_asset(self, asset: Asset) -> None:
        self.assets[asset.asset_id] = asset

    def get_asset(self, asset_id: str) -> Asset | None:
        return self.assets.get(asset_id)

    def add_finding(self, finding: Finding) -> None:
        self.findings[finding.finding_id] = finding

    def add_evidence(self, evidence_id: str, data: dict[str, Any]) -> None:
        self.evidence[evidence_id] = data

    def add_correlated_finding(self, finding: Any) -> None:
        """Add a correlated finding to the context.

        Accepts either a Finding dataclass or a dict. Stored under
        ``correlated_findings`` so it is separate from raw module findings.
        """
        if not hasattr(self, "correlated_findings"):
            self.correlated_findings: dict[str, Any] = {}
        fid = getattr(finding, "finding_id", None) or finding.get("finding_id") or finding.get("id")
        self.correlated_findings[fid] = finding

    def get_correlated_findings(self) -> list[Any]:
        """Return all correlated findings added to this context."""
        return list(getattr(self, "correlated_findings", {}).values())

    def get_coverage_summary(self) -> dict[str, Any]:
        """Return a coverage summary for this assessment context.

        Includes asset count, finding count by severity, and distinct
        source tools/modules observed.
        """
        tools: set[str] = set()
        for f in self.findings.values():
            tools.update(f.source_modules)
        return {
            "assessment_id": self.assessment_id,
            "job_id": self.job_id,
            "assets_discovered": len(self.assets),
            "assets_scanned": len(self.assets),
            "services_scanned": 0,
            "tools_used": sorted(tools),
            "tools_count": len(tools),
            "total_findings": len(self.findings),
            "findings_by_severity": {
                "critical": sum(1 for f in self.findings.values() if f.severity == "critical"),
                "high": sum(1 for f in self.findings.values() if f.severity == "high"),
                "medium": sum(1 for f in self.findings.values() if f.severity == "medium"),
                "low": sum(1 for f in self.findings.values() if f.severity == "low"),
                "informational": sum(
                    1 for f in self.findings.values() if f.severity == "informational"
                ),
            },
            "gap_count": 0,
        }

    def set_module_result(self, module_id: str, result: Any) -> None:
        self.module_results[module_id] = result

    def get_module_result(self, module_id: str) -> Any:
        return self.module_results.get(module_id)

    def log(self, module_id: str, message: str, level: str = "info") -> None:
        self.execution_log.append(
            {
                "module": module_id,
                "message": message,
                "level": level,
                "at": _now_utc(),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbook": self.playbook_id,
            "assessment_id": self.assessment_id,
            "job_id": self.job_id,
            "status": "completed",
            "target": self.target,
            "scope_id": self.scope_id,
            "profile": self.profile,
            "summary": {
                "assets_discovered": len(self.assets),
                "findings": {
                    "critical": sum(1 for f in self.findings.values() if f.severity == "critical"),
                    "high": sum(1 for f in self.findings.values() if f.severity == "high"),
                    "medium": sum(1 for f in self.findings.values() if f.severity == "medium"),
                    "low": sum(1 for f in self.findings.values() if f.severity == "low"),
                    "informational": sum(
                        1 for f in self.findings.values() if f.severity == "informational"
                    ),
                },
                "total_findings": len(self.findings),
            },
            "dns": self.module_results.get("dns_intelligence", {}),
            "ip_intelligence": self.module_results.get("ip_intelligence", {}),
            "tls": self.module_results.get("tls_intelligence", {}),
            "network": self.module_results.get("network_discovery", {}),
            "web": self.module_results.get("web_reconnaissance", {}),
            "findings": [f.__dict__ for f in self.findings.values()],
            "assets": [a.__dict__ for a in self.assets.values()],
            "evidence": self.evidence,
            "execution": {
                "total_steps": len(self.execution_log),
                "completed": len(self.module_results),
                "failed": 0,
                "skipped": 0,
                "duration": 0.0,
            },
            "artifacts": list(self.evidence.keys()),
            "recommended_next_playbooks": self._recommend_next(),
        }

    def _recommend_next(self) -> list[str]:
        """Suggest follow-up playbooks based on discoveries."""
        recs: list[str] = []
        has_web = any(
            a.asset_type in ("service", "url")
            and "http" in str(a.attributes.get("protocol", "")).lower()
            for a in self.assets.values()
        )
        has_tls = any(a.asset_type == "certificate" for a in self.assets.values())
        if has_web:
            recs.append("web_recon")
        if has_tls:
            recs.append("tls_recon")
        if any(a.asset_type == "ip" for a in self.assets.values()):
            recs.append("network_recon")
        return recs
