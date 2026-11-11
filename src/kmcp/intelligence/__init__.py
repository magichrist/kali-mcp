"""Intelligence layer for Kali MCP v2.0.0.

Provides finding correlation, asset relationship building, verification state
management, coverage tracking, and assessment diffing so the server understands
assessments rather than just launching binaries.
"""

from kmcp.intelligence.assessment_diff import AssessmentDiffer, DiffResult
from kmcp.intelligence.asset_relationships import AssetRelationshipBuilder
from kmcp.intelligence.coverage_tracker import CoverageTracker
from kmcp.intelligence.finding_correlation import Finding, FindingCorrelator
from kmcp.intelligence.verification_states import VerificationStates

__all__ = [
    "AssessmentDiffer",
    "AssetRelationshipBuilder",
    "CoverageTracker",
    "DiffResult",
    "Finding",
    "FindingCorrelator",
    "VerificationStates",
]
