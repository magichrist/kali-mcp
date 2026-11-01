"""Plaintext inter-agent vault for Kali MCP (Phase 1 foundation).

This is intentionally simple: plaintext storage with restrictive filesystem perms.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import config

VAULT_ROOT = Path(config.artifact_dir) / "vault"


def ensure_vault_dirs() -> None:
    VAULT_ROOT.mkdir(parents=True, exist_ok=True)
    index = VAULT_ROOT / "index.json"
    if not index.exists():
        index.write_text(json.dumps({"count": 0, "entries": []}, indent=2))


def _update_index(entry: dict[str, Any]) -> None:
    index = VAULT_ROOT / "index.json"
    try:
        data = json.loads(index.read_text())
    except Exception:
        data = {"count": 0, "entries": []}
    data.setdefault("entries", []).append(entry)
    data["count"] = len(data.get("entries", []))
    index.write_text(json.dumps(data, indent=2))


def vault_write(category: str, name: str, content: Any) -> None:
    category_dir = VAULT_ROOT / category
    category_dir.mkdir(parents=True, exist_ok=True)
    path = category_dir / f"{name}.json"
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    _update_index({"category": category, "name": name, "path": str(path)})


def vault_read(category: str, name: str) -> str:
    p = VAULT_ROOT / category / f"{name}.json"
    if not p.exists():
        return json.dumps({"error": "not found"}, indent=2)
    return p.read_text(encoding="utf-8")
