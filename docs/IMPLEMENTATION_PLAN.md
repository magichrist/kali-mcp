# Kali MCP Server — Implementation Plan

**Based on:** Feature roadmap (Approach C — Hybrid)  
**Status:** Ready for implementation  
**Order:** Foundation → Wrappers+Infrastructure → Orchestration → Parallel Fan-Out

---

## Phase 1 — Foundation (Week 1)

**Goal:** SQLite DB + vault directory + normalization mixin — the infrastructure all wrappers depend on.

### Tasks
1. Create `data/` directory + SQLite schema manager (`db/manager.py`)
   - `targets`, `scans`, `findings`, `credentials` tables
   - Connection manager with WAL mode, busy timeout
   - Idempotent `CREATE TABLE IF NOT EXISTS` on init
2. Create vault directory structure (`artifacts/vault/`)
   - `credentials/`, `findings/`, `evidence/`, `notes/`
   - `index.json` generator
   - File permissions: dir `0700`, files `0600`
3. Create `NormalizedToolMixin` in `tools/normalization.py`
   - `normalize()` abstract method
   - Output contract wrapper (raw + normalized + parsed_at + parse_success)
4. Add config env vars: `MCP_DB_PATH`, `MCP_DB_ENABLED`
5. Register SQLite + vault as MCP resources (`kali://db/stats`, `kali://vault/index`)

### Deliverables
- `docs/superpowers/specs/2026-10-31-foundation-design.md` (this spec)
- `db/manager.py` — SQLite connection + schema
- `tools/normalization.py` — NormalizedToolMixin
- Vault directory + index generator
- Unit tests for DB CRUD + vault read/write

---

## Phase 2 — New Tool Wrappers + Infrastructure Integration (Week 2-3)

**Goal:** Add 10+ Kali tool wrappers, each emitting normalized output + writing to SQLite + vault.

### Wrappers (in priority order)
1. `msfconsole` — Metasploit
2. `hydra` — brute-force
3. `hashcat` — hash cracking
4. `gobuster` — directory brute-force
5. `masscan` — fast port scan
6. `john` — password cracking
7. `bettercap` — MITM/sniffing
8. `responder` — LLMNR/NBT-NS poisoning
9. `zap` / `owasp-zap` — web app scanning
10. `wfuzz` — web fuzzing
11. `dirb` — directory brute-force
12. `medusa` — network brute-force

### Per wrapper
- `tools/<name>.py` extending `BaseTool` + `NormalizedToolMixin`
- JSON schema input with validated params
- `build_command()` returns `list[str]`
- `execute()` runs via engine, normalizes output, writes to SQLite + vault
- Registered in `tools/__init__.py` `ALL_TOOLS`

### Integration
- Every wrapper writes `scans` + `findings` rows to SQLite
- Every wrapper deposits normalized JSON to `vault/findings/<target>/<timestamp>.json`
- Credentials (from hydra/hashcat/john/responder) → `credentials` table + `vault/credentials/`

### Deliverables
- 12 new tool wrapper files
- Each wrapper tested (validation + build_command + execute)
- All wrappers registered and listed by `just tools`
- SQLite + vault populated on each run

---

## Phase 3 — Workflow Orchestration / Playbooks (Week 4)

**Goal:** Chain tools into recon, web-app, and AD playbooks.

### Playbooks
1. `playbook_recon` — external reconnaissance (subfinder→httpx→masscan→whatweb→nmap→nuclei→sqlmap)
2. `playbook_webapp` — web app assessment (katana→arjun→ffuf→nuclei→sqlmap→commix)
3. `playbook_ad` — AD assessment (enum4linux→bloodhound→netexec→crackmapexec)

### Playbook Engine
- `tools/playbook_engine.py` — sequential + parallel step execution
- Progress reporting per step via MCP `ctx.report_progress()`
- Error isolation: failed step doesn't abort playbook
- Resume: skip completed steps (tracked in SQLite `scans` table)

### MCP Tools
- `playbook_recon`, `playbook_webapp`, `playbook_ad`
- `playbook_list`, `playbook_status`

### Deliverables
- 3 playbook tools registered
- Playbook engine with progress + error handling
- Integration tests: run playbook against mock targets, verify SQLite + vault entries

---

## Phase 4 — Parallel Execution & Fan-Out (Week 5)

**Goal:** Concurrent multi-tool execution with result aggregation.

### Tool
- `parallel_execute` — run N tools concurrently, aggregate + deduplicate
- Bounded by existing engine semaphore
- Per-sub-tool progress callbacks

### Aggregation
- Dedup open ports by (target, port, protocol)
- Dedup vulnerabilities by (target, template_id)
- Dedup credentials by (target, service, username)

### Deliverables
- `parallel_execute` MCP tool
- `parallel_status` tool
- Unit tests for concurrency + aggregation + error isolation

---

## Phase 5 — Polish & Testing (Week 6)

**Goal:** Harden everything, fix bugs, add docs.

### Tasks
- Run `just test` (existing smoke tests) — all must pass
- Add tests for all new features
- Run ruff linting
- Update README.md with new tools and features
- Update `docs/FEATURE_ROADMAP.md` with completion status
- Performance check: concurrent execution doesn't starve the event loop

---

## Definition of Done

- [ ] SQLite DB created on first run, schema idempotent
- [ ] Vault directory + index.json working
- [ ] ≥10 new tool wrappers registered, callable via MCP
- [ ] Every wrapper emits normalized JSON output
- [ ] Every wrapper writes findings to SQLite + vault
- [ ] ≥2 playbooks run end-to-end
- [ ] `parallel_execute` runs tools concurrently + aggregates
- [ ] All existing tests pass
- [ ] New tests pass for every feature
- [ ] README updated with new tool inventory

---

## Files to Create/Modify

### New files
```
db/manager.py                    # SQLite connection + schema
tools/normalization.py           # NormalizedToolMixin
tools/msfconsole.py
tools/hydra.py
tools/hashcat.py
tools/john.py
tools/gobuster.py
tools/masscan.py
tools/bettercap.py
tools/responder.py
tools/zap.py
tools/wfuzz.py
tools/dirb.py
tools/medusa.py
tools/playbook_engine.py
tools/playbook_recon.py
tools/playbook_webapp.py
tools/playbook_ad.py
tools/parallel_execute.py
artifacts/vault/                 # directory structure
data/                            # SQLite DB location
docs/superpowers/specs/          # this spec + per-feature specs
```

### Modified files
```
tools/__init__.py                # Add all new tools to ALL_TOOLS
server.py                        # Register new MCP resources/tools if needed
config.py                        # Add MCP_DB_PATH, MCP_DB_ENABLED
README.md                        # Update tool inventory table
docs/FEATURE_ROADMAP.md          # Mark phases complete
```
