"""Integration tests for the vault MCP tools (tools/vault_tool.py)."""

from __future__ import annotations

import json

import pytest

from kali_mcp.tools.vault_tool import (
    VaultDeleteTool,
    VaultListTool,
    VaultQueryTool,
    VaultReadTool,
    VaultStatsTool,
    VaultWriteTool,
)


@pytest.fixture()
def vault_env(tmp_path, monkeypatch):
    from kali_mcp.utils import vault as v

    monkeypatch.setattr(v, "VAULT_ROOT", tmp_path / "vault")
    v.ensure_vault_dirs()
    yield v


def _stdout(resp: dict) -> dict:
    """Unwrap the MCP response → ExecutionResult → stdout payload."""
    outer = json.loads(resp["content"][0]["text"])
    return json.loads(outer["stdout"])


async def test_write_then_read_roundtrip(vault_env):
    write = VaultWriteTool()
    read = VaultReadTool()

    resp = await write.execute(
        {
            "category": "handoff",
            "name": "stage2_targets",
            "content": {"hosts": ["10.0.0.1", "10.0.0.2"]},
            "target": "example.com",
        }
    )
    assert resp["isError"] is False
    assert _stdout(resp)["status"] == "stored"

    resp = await read.execute({"category": "handoff", "name": "stage2_targets"})
    assert _stdout(resp) == {"hosts": ["10.0.0.1", "10.0.0.2"]}


async def test_write_accepts_json_string_and_plain_text(vault_env):
    write = VaultWriteTool()
    read = VaultReadTool()

    # JSON object stored as JSON, read back as JSON
    await write.execute(
        {
            "category": "notes",
            "name": "as_string",
            "content": '{"key": "value"}',
        }
    )
    resp = await read.execute({"category": "notes", "name": "as_string"})
    assert _stdout(resp) == {"key": "value"}

    # plain key=value text stored verbatim — never wrapped into a JSON doc
    await write.execute(
        {"category": "notes", "name": "plain", "content": "key1=value1\nkey2=value2"}
    )
    resp = await read.execute({"category": "notes", "name": "plain"})
    payload = _stdout(resp)
    assert payload["content"] == "key1=value1\nkey2=value2"
    assert payload["category"] == "notes" and payload["name"] == "plain"


async def test_unstructured_and_array_dumps(vault_env):
    """Agents can dump any input: JSON objects, raw JSON (even non-object),
    or completely unstructured text — everything round-trips."""
    write = VaultWriteTool()
    read = VaultReadTool()
    query = VaultQueryTool()

    # Raw JSON that is not an object (array) — accepted natively
    await write.execute(
        {
            "category": "dump_test",
            "name": "array",
            "content": [1, "two", {"x": None}, [3, 4]],
        }
    )
    resp = await read.execute({"category": "dump_test", "name": "array"})
    assert _stdout(resp) == [1, "two", {"x": None}, [3, 4]]

    # Completely unstructured free text — stored verbatim, wrapped for transport
    messy = "TODO: check 10.0.0.1:22\nprobably open?? verify w/ nmap"
    await write.execute({"category": "dump_test", "name": "messy", "content": messy})
    resp = await read.execute({"category": "dump_test", "name": "messy"})
    payload = _stdout(resp)
    assert payload["content"] == messy

    # Free-text search reaches into both storage shapes
    assert _stdout(await query.execute({"search": "two"}))["count"] == 1
    assert _stdout(await query.execute({"search": "nmap"}))["count"] == 1
    assert _stdout(await query.execute({"search": "TODO"}))["count"] == 1


async def test_read_missing_returns_error(vault_env):
    read = VaultReadTool()
    resp = await read.execute({"category": "notes", "name": "missing"})
    assert resp["isError"] is True


async def test_query_finds_subagent_data(vault_env):
    write = VaultWriteTool()
    query = VaultQueryTool()

    await write.execute(
        {
            "category": "findings",
            "name": "nmap_10_0_0_1",
            "content": {"ports": [22, 80]},
            "target": "10.0.0.1",
            "tool": "nmap",
        }
    )
    resp = await query.execute({"target": "10.0.0.1"})
    payload = _stdout(resp)
    assert payload["count"] == 1
    assert payload["entries"][0]["name"] == "nmap_10_0_0_1"

    resp = await query.execute({"search": "ports"})
    assert _stdout(resp)["count"] == 1

    # multi-category filter (comma-separated)
    resp = await query.execute({"category": "findings, notes"})
    assert _stdout(resp)["count"] == 1


async def test_list_and_stats(vault_env):
    write = VaultWriteTool()
    listing = VaultListTool()
    stats = VaultStatsTool()

    await write.execute({"category": "notes", "name": "a", "content": {"v": 1}})
    await write.execute({"category": "findings", "name": "b", "content": {"v": 2}})

    listed = _stdout(await listing.execute({}))
    assert listed["count"] == 2

    st = _stdout(await stats.execute({}))
    assert st["total"] == 2
    assert set(st["by_category"]) == {"notes", "findings"}


async def test_delete_roundtrip(vault_env):
    write = VaultWriteTool()
    delete = VaultDeleteTool()

    await write.execute({"category": "notes", "name": "tmp", "content": {"v": 1}})
    resp = await delete.execute({"category": "notes", "name": "tmp"})
    assert _stdout(resp)["deleted"] is True

    resp = await delete.execute({"category": "notes", "name": "tmp"})
    assert resp["isError"] is True


async def test_read_truncates_oversized_rows(vault_env):
    """Rows > max_bytes come back truncated with paging pointers."""
    write = VaultWriteTool()
    read = VaultReadTool()

    big = "Z" * (2 * 1024 * 1024)
    await write.execute(
        {"category": "big", "name": "blob_2MB", "content": {"blob": big}}
    )

    # default cap (1MB) → truncated with metadata
    resp = await read.execute({"category": "big", "name": "blob_2MB"})
    payload = _stdout(resp)
    assert payload["truncated"] is True
    assert payload["total_bytes"] > 1024 * 1024
    assert len(payload["content"]) == payload["returned_bytes"]
    assert payload["path"].endswith("blob_2MB.json")
    assert "file_read" in payload["hint"]

    # explicit small cap
    resp = await read.execute(
        {"category": "big", "name": "blob_2MB", "max_bytes": 4096}
    )
    payload = _stdout(resp)
    assert payload["truncated"] is True
    assert len(payload["content"]) == 4096

    # raised cap → full content
    resp = await read.execute(
        {"category": "big", "name": "blob_2MB", "max_bytes": 3 * 1024 * 1024}
    )
    payload = _stdout(resp)
    assert payload.get("truncated") is not True
    assert payload["blob"] == big

    # small rows are never truncated
    await write.execute({"category": "big", "name": "small", "content": {"v": 1}})
    resp = await read.execute({"category": "big", "name": "small"})
    assert _stdout(resp).get("truncated") is not True


async def test_write_rejects_oversized_rows(vault_env, monkeypatch):
    """vault_write surfaces the size ceiling as a structured error."""
    import dataclasses

    from kali_mcp.config import config as real_config
    from kali_mcp.utils import vault as v

    small = dataclasses.replace(real_config, vault_max_row_bytes=1024)
    monkeypatch.setattr("kali_mcp.utils.vault.config", small)

    write = VaultWriteTool()
    resp = await write.execute(
        {"category": "big", "name": "too_big", "content": "x" * 4096}
    )
    assert resp["isError"] is True
    details = json.loads(resp["content"][0]["text"])["details"]
    assert "vault row too large" in details
    assert "MCP_VAULT_MAX_ROW_BYTES" in details


async def test_validation_errors_surface(vault_env):
    write = VaultWriteTool()
    resp = await write.execute({"category": "", "name": "", "content": None})
    assert resp["isError"] is True
