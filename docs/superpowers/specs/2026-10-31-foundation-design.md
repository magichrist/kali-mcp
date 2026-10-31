# Kali MCP Server — Foundation Design Spec (2026-10-31)

This document codifies the Foundation phase of the Kali MCP Server implementation as described in the implementation plan.

Overview
- Phase 1 establishes the core persistence, normalization, and configuration surface that all tool wrappers rely on.
- The foundation enables deterministic, auditable storage of targets, scans, findings, credentials, and inter-agent vault entries.

Key Components Implemented in Foundation
- SQLite database with a stable schema for:
  - targets
  - scans
  - findings
  - credentials
  The DB is opened with WAL mode and a connection pool that is safe for multi-threaded use by the MCP engine.
- Vault (artifacts/vault) as a plaintext inter-agent knowledge base with structure for:
  - credentials/
  - findings/
  - evidence/
  - notes/
  - index.json for quick discovery; index is regenerated on writes/deletes.
- Normalization layer: NormalizedToolMixin-based per-tool normalization contract is implemented to emit structured JSON under stdout.
- Configuration surface exposes MCP_DB_PATH and MCP_DB_ENABLED env vars to control persistence.
- Registration of resources for MCP consumption (e.g., kali://db/stats and kali://vault/index).

Deliverables per spec
- docs/superpowers/specs/2026-10-31-foundation-design.md (this document)
- db/manager.py (SQLite connection + schema) – already implemented and wired via config
- tools/normalization.py (NormalizedToolMixin) – already implemented
- Vault directory with write/index helpers (artifacts/vault/index.json) – implemented in utils/vault.py and wired via server startup
- Unit tests for DB CRUD and vault read/write – to be added as part of Phase 1 test suite

Rationale and constraints
- Per the plan, the foundation uses a simple, auditable storage model: SQLite for structured data and a plaintext vault for inter-agent sharing.
- Encryption is intentionally not applied in this foundation; access limits rely on filesystem permissions and runtime isolation.
- The integration pattern ensures that wrappers write findings to both the DB and the vault, enabling later phases to build on top of the same canonical model.

Next steps
- Ensure tests cover idempotent DB creation and vault index regeneration.
- Validate that env-based configuration paths resolve correctly in all environments (dev, CI, prod).
- Extend tests to cover vault search and basic credential finding flows.

This spec anchors the Foundation implementation and serves as the canonical reference for all subsequent phases.
