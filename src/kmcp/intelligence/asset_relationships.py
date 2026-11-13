"""Asset Relationship Builder — constructs the asset graph edges.

Takes discovered assets and their attributes and creates typed edges
(resolves_to, contains, uses_technology, shared_by, child_of, supports) with
confidence scores and timestamps. Prevents duplicate edges via upsert behavior.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class AssetNode:
    """A node in the asset graph."""

    asset_id: str
    asset_type: str  # domain | ip | subdomain | service | technology | url
    name: str
    scope: str = "in-scope"
    attributes: dict[str, Any] = field(default_factory=dict)
    first_seen: str = field(default_factory=_now_utc)
    last_seen: str = field(default_factory=_now_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "name": self.name,
            "scope": self.scope,
            "attributes": self.attributes,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


@dataclass
class RelationshipEdge:
    """A typed edge between two asset nodes."""

    source_asset_id: str
    target_asset_id: str
    relationship: str  # resolves_to | contains | uses_technology | shared_by | child_of | supports
    confidence: float = 0.5
    first_seen: str = field(default_factory=_now_utc)
    last_seen: str = field(default_factory=_now_utc)
    source_tool: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_asset_id": self.source_asset_id,
            "target_asset_id": self.target_asset_id,
            "relationship": self.relationship,
            "confidence": self.confidence,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "source_tool": self.source_tool,
        }


class AssetRelationshipBuilder:
    """Builds and queries asset graph relationships."""

    # Valid relationship types
    VALID_RELATIONSHIPS: ClassVar[set[str]] = {
        "resolves_to",
        "contains",
        "uses_technology",
        "shared_by",
        "child_of",
        "supports",
    }

    def __init__(self) -> None:
        self._assets: dict[str, AssetNode] = {}
        self._relationships: dict[str, RelationshipEdge] = {}

    # ── public API ────────────────────────────────────────────────────

    def add_asset(
        self,
        asset_id: str,
        asset_type: str,
        name: str,
        scope: str = "in-scope",
        attributes: dict[str, Any] | None = None,
    ) -> AssetNode:
        """Register or update an asset node."""
        now = _now_utc()
        if asset_id in self._assets:
            node = self._assets[asset_id]
            node.asset_type = asset_type
            node.name = name
            node.scope = scope
            if attributes:
                node.attributes.update(attributes)
            node.last_seen = now
        else:
            node = AssetNode(
                asset_id=asset_id,
                asset_type=asset_type,
                name=name,
                scope=scope,
                attributes=attributes or {},
                first_seen=now,
                last_seen=now,
            )
            self._assets[asset_id] = node
        return node

    def add_relationship(
        self,
        source_asset_id: str,
        target_asset_id: str,
        relationship: str,
        confidence: float = 0.5,
        source_tool: str | None = None,
    ) -> RelationshipEdge:
        """Add or update a relationship edge (upsert — no duplicates)."""
        if relationship not in self.VALID_RELATIONSHIPS:
            raise ValueError(
                f"Invalid relationship type: {relationship}. "
                f"Valid: {sorted(self.VALID_RELATIONSHIPS)}"
            )

        key = f"{source_asset_id}|{target_asset_id}|{relationship}"
        now = _now_utc()

        if key in self._relationships:
            edge = self._relationships[key]
            edge.confidence = confidence
            edge.last_seen = now
            if source_tool is not None:
                edge.source_tool = source_tool
        else:
            edge = RelationshipEdge(
                source_asset_id=source_asset_id,
                target_asset_id=target_asset_id,
                relationship=relationship,
                confidence=confidence,
                first_seen=now,
                last_seen=now,
                source_tool=source_tool,
            )
            self._relationships[key] = edge
        return edge

    def build_graph(self, ctx: Any | None = None) -> dict[str, Any]:
        """Return the full graph as {assets, relationships}.

        If a context with ``assets`` and ``findings`` is provided, those are
        merged into the graph before returning.
        """
        assets = [node.to_dict() for node in self._assets.values()]
        relationships = [edge.to_dict() for edge in self._relationships.values()]

        if ctx is not None:
            # Merge assets from context
            ctx_assets = getattr(ctx, "assets", None)
            if ctx_assets:
                for aid, asset in ctx_assets.items():
                    self.add_asset(
                        asset_id=asset.asset_id,
                        asset_type=asset.asset_type,
                        name=asset.name,
                        scope=asset.scope,
                        attributes=asset.attributes,
                    )
            # Merge relationships from context assets
            for aid, asset in (ctx_assets or {}).items():
                for rel in getattr(asset, "relationships", []):
                    self.add_relationship(
                        source_asset_id=aid,
                        target_asset_id=rel.get("target_asset_id", aid),
                        relationship=rel.get("relationship", "related_to"),
                        confidence=rel.get("confidence", 0.5),
                        source_tool=rel.get("source_tool"),
                    )
            assets = [node.to_dict() for node in self._assets.values()]
            relationships = [edge.to_dict() for edge in self._relationships.values()]

        return {"assets": assets, "relationships": relationships}

    def query_relationships(
        self, asset_id: str, relationship_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Return relationship edges involving the given asset.

        Args:
            asset_id: The asset to query.
            relationship_type: Optional filter by relationship type.

        Returns:
            List of edge dicts where the asset is source or target.
        """
        results: list[dict[str, Any]] = []
        for edge in self._relationships.values():
            if edge.source_asset_id != asset_id and edge.target_asset_id != asset_id:
                continue
            if relationship_type and edge.relationship != relationship_type:
                continue
            results.append(edge.to_dict())
        return results

    def get_asset(self, asset_id: str) -> AssetNode | None:
        """Return an asset node by ID."""
        return self._assets.get(asset_id)

    def list_assets(self) -> list[dict[str, Any]]:
        """Return all asset nodes."""
        return [node.to_dict() for node in self._assets.values()]

    def list_relationships(self) -> list[dict[str, Any]]:
        """Return all relationship edges."""
        return [edge.to_dict() for edge in self._relationships.values()]
