"""Unit tests for the Asset Relationship Builder (asset_relationships.py)."""

from __future__ import annotations

import pytest

from kmcp.intelligence import AssetRelationshipBuilder


@pytest.fixture()
def builder() -> AssetRelationshipBuilder:
    return AssetRelationshipBuilder()


# ── Asset registration ───────────────────────────────────────────────


def test_add_asset_creates_node(builder):
    node = builder.add_asset("d1", "domain", "example.com")
    assert node.asset_id == "d1"
    assert node.asset_type == "domain"
    assert node.name == "example.com"
    assert node.scope == "in-scope"


def test_add_asset_updates_existing(builder):
    builder.add_asset("d1", "domain", "example.com")
    node = builder.add_asset("d1", "domain", "example.com", scope="out-of-scope")
    assert node.scope == "out-of-scope"
    # Should still be only one asset
    assert len(builder.list_assets()) == 1


def test_add_asset_with_attributes(builder):
    node = builder.add_asset(
        "ip1", "ip", "127.0.0.1", attributes={"cidr": "127.0.0.0/24", "asn": "AS1234"}
    )
    assert node.attributes["cidr"] == "127.0.0.0/24"
    assert node.attributes["asn"] == "AS1234"


# ── Relationships ────────────────────────────────────────────────────


def test_add_relationship_creates_edge(builder):
    builder.add_asset("d1", "domain", "example.com")
    builder.add_asset("ip1", "ip", "127.0.0.1")
    edge = builder.add_relationship("d1", "ip1", "resolves_to", 0.9, "subfinder")
    assert edge.source_asset_id == "d1"
    assert edge.target_asset_id == "ip1"
    assert edge.relationship == "resolves_to"
    assert edge.confidence == 0.9
    assert edge.source_tool == "subfinder"


def test_add_relationship_prevents_duplicates_upsert(builder):
    builder.add_asset("d1", "domain", "example.com")
    builder.add_asset("ip1", "ip", "127.0.0.1")
    builder.add_relationship("d1", "ip1", "resolves_to", 0.9, "subfinder")
    edge_count_before = len(builder.list_relationships())
    # Same relationship again → upsert, not duplicate
    builder.add_relationship("d1", "ip1", "resolves_to", 0.95, "dnsx")
    assert len(builder.list_relationships()) == edge_count_before
    edges = builder.list_relationships()
    assert edges[0]["confidence"] == 0.95
    assert edges[0]["source_tool"] == "dnsx"


def test_add_relationship_invalid_type_raises(builder):
    builder.add_asset("d1", "domain", "example.com")
    builder.add_asset("ip1", "ip", "127.0.0.1")
    with pytest.raises(ValueError):
        builder.add_relationship("d1", "ip1", "invalid_type", 0.5, "tool")


# ── Graph building ───────────────────────────────────────────────────


def test_build_graph_returns_assets_and_relationships(builder):
    builder.add_asset("d1", "domain", "example.com")
    builder.add_asset("ip1", "ip", "127.0.0.1")
    builder.add_relationship("d1", "ip1", "resolves_to", 0.9, "subfinder")
    graph = builder.build_graph()
    assert "assets" in graph
    assert "relationships" in graph
    assert len(graph["assets"]) == 2
    assert len(graph["relationships"]) == 1


def test_query_relationships_by_asset(builder):
    builder.add_asset("d1", "domain", "example.com")
    builder.add_asset("ip1", "ip", "127.0.0.1")
    builder.add_asset("svc1", "service", "HTTP:443")
    builder.add_relationship("d1", "ip1", "resolves_to", 0.9, "subfinder")
    builder.add_relationship("ip1", "svc1", "contains", 0.95, "nmap")

    # Query relationships where ip1 is source or target
    rels = builder.query_relationships("ip1")
    assert len(rels) == 2

    # Filter by type
    rels = builder.query_relationships("ip1", "contains")
    assert len(rels) == 1
    assert rels[0]["relationship"] == "contains"


def test_query_relationships_nonexistent_asset(builder):
    rels = builder.query_relationships("nonexistent")
    assert rels == []


# ── Relationship types ───────────────────────────────────────────────


def test_all_valid_relationship_types(builder):
    builder.add_asset("a1", "domain", "example.com")
    builder.add_asset("a2", "ip", "127.0.0.1")
    builder.add_asset("a3", "service", "HTTP:443")
    builder.add_asset("a4", "subdomain", "app.example.com")
    builder.add_asset("a5", "technology", "Apache")

    builder.add_relationship("a1", "a2", "resolves_to", 0.9, "t1")
    builder.add_relationship("a2", "a3", "contains", 0.95, "t2")
    builder.add_relationship("a3", "a5", "uses_technology", 0.8, "t3")
    builder.add_relationship("a2", "a1", "shared_by", 0.7, "t4")
    builder.add_relationship("a4", "a1", "child_of", 0.99, "t5")

    graph = builder.build_graph()
    rel_types = {r["relationship"] for r in graph["relationships"]}
    assert rel_types == {"resolves_to", "contains", "uses_technology", "shared_by", "child_of"}


# ── Context merge ────────────────────────────────────────────────────


def test_build_graph_merges_context_assets(builder):
    class FakeAsset:
        def __init__(self):
            self.asset_id = "ctx_asset"
            self.asset_type = "ip"
            self.name = "127.0.0.1"
            self.scope = "in-scope"
            self.attributes = {}
            self.relationships = []

    class FakeCtx:
        assets = {"ctx_asset": FakeAsset()}

    graph = builder.build_graph(FakeCtx())
    asset_ids = {a["asset_id"] for a in graph["assets"]}
    assert "ctx_asset" in asset_ids
