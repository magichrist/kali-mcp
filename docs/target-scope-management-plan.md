# Kali MCP Server — Target & Scope Management Plan (SQLite)

**Goal:** Give AI pentester agents a persistent, queryable record of targets, scope tags, scan history, and findings — so agents don't lose context between sessions.

**Priority:** P0  
**Persistence layer:** SQLite (chosen over JSON files per user decision)  
**Approach:** Hybrid — SQLite DB built in parallel with wrappers; wrappers write findings into it.

---

## Database Schema

Single SQLite file: `data/kali-mcp.sqlite` (configurable via `MCP_DB_PATH`)

### Table: targets
```sql
CREATE TABLE targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL UNIQUE,           -- IP, CIDR, hostname, or URL
    target_type TEXT NOT NULL,             -- ip, cidr, hostname, url, range
    scope TEXT NOT NULL DEFAULT 'in-scope', -- in-scope, out-of-scope, excluded
    tags TEXT,                              -- comma-separated: web, ad, network, wifi, client-provided
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_targets_scope ON targets(scope);
CREATE INDEX idx_targets_type ON targets(target_type);
```

### Table: scans
```sql
CREATE TABLE scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER NOT NULL REFERENCES targets(id),
    tool TEXT NOT NULL,                     -- nmap, nuclei, hydra, etc.
    command TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration REAL,
    success INTEGER DEFAULT 0,
    findings_count INTEGER DEFAULT 0,
    artifact_uri TEXT,                      -- kali://artifacts/<file>
    FOREIGN KEY (target_id) REFERENCES targets(id)
);
CREATE INDEX idx_scans_target ON scans(target_id);
CREATE INDEX idx_scans_tool ON scans(tool);
```

### Table: findings
```sql
CREATE TABLE findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER NOT NULL REFERENCES targets(id),
    scan_id INTEGER REFERENCES scans(id),
    tool TEXT NOT NULL,
    finding_type TEXT NOT NULL,             -- open_port, vulnerability, credential, directory, etc.
    severity TEXT,                          -- critical, high, medium, low, info, none
    title TEXT NOT NULL,
    description TEXT,
    evidence TEXT,                          -- normalized JSON or raw excerpt
    port INTEGER,
    service TEXT,
    url TEXT,
    status TEXT DEFAULT 'open',             -- open, verified, false-positive, remediated
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (target_id) REFERENCES targets(id),
    FOREIGN KEY (scan_id) REFERENCES scans(id)
);
CREATE INDEX idx_findings_target ON findings(target_id);
CREATE INDEX idx_findings_severity ON findings(severity);
CREATE INDEX idx_findings_status ON findings(status);
```

### Table: credentials
```sql
CREATE TABLE credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id INTEGER NOT NULL REFERENCES targets(id),
    service TEXT NOT NULL,                  -- ssh, ftp, smb, http, etc.
    username TEXT NOT NULL,
    password TEXT,                          -- plaintext (vault is plaintext per user decision)
    hash TEXT,                              -- NTLM, MD5, etc. if cracked from hash
    source_tool TEXT NOT NULL,              -- hydra, hashcat, john, responder, etc.
    captured_at TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (target_id) REFERENCES targets(id)
);
CREATE INDEX idx_credentials_target ON credentials(target_id);
CREATE INDEX idx_credentials_service ON credentials(service);
```

---

## MCP Tools for Scope Management

| Tool | Purpose | Params |
|------|---------|--------|
| `target_add` | Register a target with scope/tags | target, target_type, scope, tags, notes |
| `target_list` | List targets (filter by scope/tags) | scope, tags, target_type |
| `target_update` | Update scope/tags/notes | id, scope, tags, notes |
| `target_remove` | Remove a target | id |
| `scan_record` | Record a scan execution | target_id, tool, command, duration, success, findings_count, artifact_uri |
| `finding_add` | Add a finding manually | target_id, tool, finding_type, severity, title, description, evidence, port, service, url |
| `finding_list` | List findings (filter by target/severity/status) | target_id, severity, status, tool |
| `credential_add` | Store a discovered credential | target_id, service, username, password, hash, source_tool, notes |
| `credential_list` | List credentials (filter by target/service) | target_id, service |
| `db_query` | Ad-hoc read-only SQL query | query (SELECT only) |

---

## Integration Points

- **Wrappers:** After execution, write scan + findings rows to SQLite; deposit findings to vault
- **Playbooks:** Read targets from SQLite; write results back
- **Vault:** Cross-reference vault files with SQLite finding IDs

---

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `MCP_DB_PATH` | `data/kali-mcp.sqlite` | Path to SQLite database file |
| `MCP_DB_ENABLED` | `true` | Enable/disable SQLite persistence |

---

## Testing

- Schema creation on first run (idempotent `CREATE TABLE IF NOT EXISTS`)
- CRUD operations for targets, scans, findings, credentials
- Query filtering by scope, severity, status
- Foreign key integrity
- DB migration path for schema changes
