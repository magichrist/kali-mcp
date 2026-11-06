"""Finding Correlation Engine — deduplicate and merge observations across tools.

Groups raw observations from different tools scanning the same target into a
single normalized finding per unique issue, aggregating source tools, evidence
refs, and confidence based on corroboration count.

Confidence formula: base 0.5 + 0.1 per additional source, capped at 0.99.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


@dataclass
class Finding:
    """A normalized, correlated finding.

    Attributes:
        finding_id: Unique identifier.
        title: Human-readable finding title.
        severity: critical | high | medium | low | informational.
        confidence: 0.0–1.0 confidence score.
        validation_status: observed | suspected | validated | remediated |
            false_positive | accepted_risk.
        asset_id: Reference to the asset in the asset graph.
        source_tools: List of tools that reported this finding.
        evidence_refs: List of stored evidence artifact IDs.
        description: Human-readable description.
        finding_type: Category/type of finding (used for grouping).
        port: Port number if applicable.
        service: Service name if applicable.
        url: URL if applicable.
        first_seen: Timestamp when first observed.
        last_seen: Timestamp when last observed.
    """

    finding_id: str
    title: str
    severity: str = "informational"
    confidence: float = 0.5
    validation_status: str = "observed"
    asset_id: str | None = None
    source_tools: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    description: str = ""
    finding_type: str = ""
    port: int | None = None
    service: str | None = None
    url: str | None = None
    first_seen: str = field(default_factory=_now_utc)
    last_seen: str = field(default_factory=_now_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.finding_id,
            "title": self.title,
            "severity": self.severity,
            "confidence": self.confidence,
            "validation_status": self.validation_status,
            "asset_id": self.asset_id,
            "source_tools": self.source_tools,
            "evidence_refs": self.evidence_refs,
            "description": self.description,
            "finding_type": self.finding_type,
            "port": self.port,
            "service": self.service,
            "url": self.url,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


class FindingCorrelator:
    """Correlates raw observations from multiple tools into normalized findings."""

    BASE_CONFIDENCE = 0.5
    CORROBORATION_BONUS = 0.1
    MAX_CONFIDENCE = 0.99

    def __init__(self) -> None:
        self._correlation_metadata: dict[str, Any] = {}

    # ── public API ────────────────────────────────────────────────────

    def correlate(
        self, observations: list[dict], ctx: Any | None = None
    ) -> list[Finding]:
        """Correlate a list of raw observations into merged findings.

        Args:
            observations: List of observation dicts, each with at least
                ``title`` or ``finding_type`` plus optional ``asset_id``,
                ``tool``, ``evidence_ref``, ``severity``, ``confidence``,
                ``description``, ``port``, ``service``, ``url``.
            ctx: Optional assessment context (unused directly, reserved for
                future integration).

        Returns:
            List of merged :class:`Finding` objects.
        """
        groups = self._group_similar(observations)
        findings: list[Finding] = []
        for key, group in groups.items():
            finding = self._merge_group(group)
            findings.append(finding)

        # Sort by severity then confidence for deterministic output
        severity_order = {
            "critical": 0, "high": 1, "medium": 2, "low": 3,
            "informational": 4,
        }
        findings.sort(
            key=lambda f: (
                severity_order.get(f.severity, 99),
                -f.confidence,
                f.title,
            )
        )

        self._correlation_metadata = {
            "total_observations": len(observations),
            "total_groups": len(groups),
            "merged_findings": len(findings),
            "groups": {k: len(v) for k, v in groups.items()},
        }
        return findings

    def get_correlation_metadata(self) -> dict[str, Any]:
        """Return metadata from the last :meth:`correlate` call."""
        return dict(self._correlation_metadata)

    # ── internal: grouping ────────────────────────────────────────────

    def _group_similar(self, observations: list[dict]) -> dict[str, list[dict]]:
        """Group observations by (asset_id, normalized title/finding_type)."""
        groups: dict[str, list[dict]] = {}
        for obs in observations:
            asset_id = obs.get("asset_id") or obs.get("target") or "unknown"
            title = self._normalize_title(obs.get("title") or obs.get("finding_type") or "unknown")
            key = f"{asset_id}|{title}"
            groups.setdefault(key, []).append(obs)
        return groups

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize a finding title for similarity grouping."""
        t = title.lower().strip()
        t = re.sub(r"[^a-z0-9\s]", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    # ── internal: merging ─────────────────────────────────────────────

    def _merge_group(self, group: list[dict]) -> Finding:
        """Merge a group of similar observations into one Finding."""
        # Use the first observation as the base
        base = group[0]
        asset_id = base.get("asset_id") or base.get("target") or "unknown"
        title = base.get("title") or base.get("finding_type") or "Untitled finding"
        severity = base.get("severity", "informational")
        finding_type = base.get("finding_type", base.get("title", ""))
        description = base.get("description", "")
        port = base.get("port")
        service = base.get("service")
        url = base.get("url")

        # Aggregate source tools (dedup, preserve order)
        source_tools: list[str] = []
        for obs in group:
            tool = obs.get("tool") or obs.get("source_tool") or "unknown"
            if tool not in source_tools:
                source_tools.append(tool)

        # Aggregate evidence refs (dedup, preserve order)
        evidence_refs: list[str] = []
        for obs in group:
            ref = obs.get("evidence_ref") or obs.get("evidence_id")
            if ref and ref not in evidence_refs:
                evidence_refs.append(ref)
        # Also accept evidence_refs as a list on the observation
        for obs in group:
            refs = obs.get("evidence_refs") or []
            for ref in refs:
                if ref not in evidence_refs:
                    evidence_refs.append(ref)

        # Confidence: base 0.5 + 0.1 per additional source, capped at 0.99
        num_sources = len(source_tools)
        confidence = min(self.MAX_CONFIDENCE, self.BASE_CONFIDENCE + (num_sources - 1) * self.CORROBORATION_BONUS)
        # If an observation had a higher explicit confidence, respect it
        for obs in group:
            explicit = obs.get("confidence")
            if explicit is not None and float(explicit) > confidence:
                confidence = float(explicit)
        confidence = round(confidence, 2)

        # Timestamps: first_seen = earliest, last_seen = latest
        now = _now_utc()
        first_seen = now
        last_seen = now
        for obs in group:
            ts = obs.get("first_seen") or obs.get("created_at") or obs.get("timestamp")
            if ts:
                first_seen = min(first_seen, str(ts))
            ts = obs.get("last_seen") or obs.get("updated_at") or obs.get("timestamp")
            if ts:
                last_seen = max(last_seen, str(ts))

        finding_id = base.get("finding_id") or base.get("id")

        return Finding(
            finding_id=finding_id,
            title=title,
            severity=severity,
            confidence=confidence,
            validation_status="observed",
            asset_id=asset_id,
            source_tools=source_tools,
            evidence_refs=evidence_refs,
            description=description,
            finding_type=finding_type,
            port=port,
            service=service,
            url=url,
            first_seen=first_seen,
            last_seen=last_seen,
        )
