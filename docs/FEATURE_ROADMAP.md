# Kali MCP Server — Empowerment Feature Roadmap

**Goal:** Make AI pentester agents better at what they do — not restrict them. Add tools, orchestration, shared state, and inter-agent knowledge sharing so agents can run full engagements autonomously.

**Approach:** Hybrid (Approach C) — new Kali tool wrappers, SQLite persistence, plaintext vault, per-tool normalization, playbooks, and parallel fan-out all built in parallel tracks.

---

## Feature Areas

| # | Area | Doc | Priority |
|---|------|-----|----------|
| 1 | New Kali Tool Wrappers | `docs/tool-wrappers-plan.md` | P0 |
| 2 | Result Normalization (per-tool) | `docs/result-normalization-plan.md` | P0 |
| 3 | Target & Scope Management (SQLite) | `docs/target-scope-management-plan.md` | P0 |
| 4 | Credential & Evidence Vault (plaintext, inter-agent) | `docs/credential-evidence-vault-plan.md` | P0 |
| 5 | Workflow Orchestration / Playbooks | `docs/orchestration-playbooks-plan.md` | P1 |
| 6 | Parallel Execution & Fan-Out | `docs/parallel-execution-plan.md` | P1 |

---

## Cross-Cutting Design Decisions (locked in)

| Decision | Value | Rationale |
|----------|-------|-----------|
| Tool wrappers first | Yes | User priority — agents need more raw capability immediately |
| Normalization scope | Per-tool | Each tool's output gets its own structured schema; simpler to implement than a unified schema |
| Persistence layer | SQLite | Structured, queryable, ACID for targets, scope, findings |
| Vault encryption | Plaintext + filesystem perms | No key management; agents share knowledge freely via filesystem |
| Vault purpose | Inter-agent knowledge base | Agents deposit findings; other agents read them when needed |
| Approach | Hybrid (C) | All tracks in parallel; wrappers write into SQLite + vault from day one |

---

## Success Criteria

- [x] ≥10 new Kali tool wrappers registered and callable via MCP (12 added: msfconsole, hydra, hashcat, gobuster, masscan, john, zap, wfuzz, dirb, medusa, bettercap, responder)
- [x] Each wrapper returns per-tool normalized JSON output (`tools/persist.py` contract: raw + normalized + parsed_at + parse_success; structured parsers for creds, ports, and web paths)
- [x] SQLite DB stores targets, scope tags, scan history, findings (and credentials)
- [x] Plaintext vault directory enables agent-to-agent knowledge sharing (every run deposits findings; credentials written to `vault/credentials/`; browsable via `kali://vault/index`)
- [x] ≥2 playbooks (recon, web-app) chain multiple tools as one flow (recon, web-app, AD + custom `playbook_engine` with `{{target}}` substitution and resume)
- [x] Parallel fan-out runs multiple recon tools concurrently (`parallel_execute` + `parallel_status`, with result aggregation/dedup)
- [x] All existing tests still pass; new tests added for each feature (pytest suite in `tests/`: unit + integration + e2e)

---

## Implementation Phases

### Phase 1 — Foundation (P0) ✅
- SQLite schema + connection manager (`db/manager.py`)
- Plaintext vault directory + read/write helpers (`utils/vault.py`)
- Per-tool normalization schema + base mixin (`tools/normalization.py`)
- `MCP_DB_PATH` / `MCP_DB_ENABLED` config
- MCP resources: `kali://db/stats`, `kali://vault/index`

### Phase 2 — Expansion (P0) ✅
- 12 tool wrappers: msfconsole, hydra, hashcat, gobuster, masscan, john, zap, wfuzz, dirb, medusa, bettercap, responder
- All wrappers emit normalized output; central + per-finding persistence to SQLite + vault
- Credentials (hydra/medusa/john/hashcat) → `credentials` table + `vault/credentials/`

### Phase 3 — Orchestration (P1) ✅
- `playbook_recon`, `playbook_webapp`, `playbook_ad` registered as MCP tools
- `playbook_engine` for custom playbooks (with `{{target}}` substitution + resume)
- `playbook_list`, `playbook_status` for discovery and run tracking

### Phase 4 — Parallel Fan-Out (P1) ✅
- `parallel_execute` MCP tool with error isolation
- Result aggregation + deduplication (ports/vulns)
- `parallel_status` job tracking

---

*Specs are detailed in the individual plan docs listed above.*