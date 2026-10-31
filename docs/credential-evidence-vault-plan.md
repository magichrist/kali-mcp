# Kali MCP Server — Credential & Evidence Vault Plan (Inter-Agent Knowledge Base)

**Goal:** Give AI agents a shared knowledge base where they can deposit findings, credentials, and evidence — so other agents can read them when needed. Plaintext + filesystem permissions (no encryption, per user decision).

**Priority:** P0  
**Encryption:** Plaintext + filesystem perms (user decision)  
**Approach:** Hybrid — vault built in parallel with wrappers; wrappers deposit findings into it.

---

## Vault Directory Structure

```
artifacts/vault/
├── credentials/          # Discovered passwords, hashes, keys
│   ├── <target>/
│   │   └── <timestamp>.json   # {"service": "ssh", "username": "admin", "password": "...", ...}
├── findings/             # Normalized findings from tool runs
│   ├── <target>/
│   │   └── <timestamp>.json   # per-tool normalized finding
├── evidence/             # Raw artifacts (screenshots, captures, files)
│   ├── <target>/
│   │   └── <timestamp>.<ext>
├── notes/                # Free-form agent notes
│   └── <timestamp>.md
└── index.json            # Searchable index of all vault entries
```

---

## Vault MCP Tools

| Tool | Purpose | Params |
|------|---------|--------|
| `vault_write` | Deposit a finding/credential/evidence to the vault | category (credentials/findings/evidence/notes), target, content (JSON/text), filename (optional) |
| `vault_read` | Read a vault entry by path | path |
| `vault_list` | List vault entries (filter by category/target) | category, target, limit |
| `vault_search` | Full-text search across vault entries | query, category, target |
| `vault_delete` | Remove a vault entry | path |

---

## Entry Format

### Credential entry (`credentials/<target>/<timestamp>.json`)
```json
{
  "id": "cred_20261031_143000",
  "category": "credentials",
  "target": "10.0.0.5",
  "service": "ssh",
  "username": "admin",
  "password": "Summer2024!",
  "hash": null,
  "source_tool": "hydra",
  "source_scan_id": 42,
  "deposited_by": "agent-1",
  "deposited_at": "2026-10-31T14:30:00Z",
  "notes": "Found on port 22, works for sudo"
}
```

### Finding entry (`findings/<target>/<timestamp>.json`)
```json
{
  "id": "finding_20261031_143001",
  "category": "findings",
  "target": "10.0.0.5",
  "tool": "nuclei",
  "finding_type": "vulnerability",
  "severity": "critical",
  "title": "Log4Shell RCE",
  "evidence": {"template_id": "cve-2021-44228", "url": "https://10.0.0.5:8080/"},
  "deposited_by": "agent-1",
  "deposited_at": "2026-10-31T14:30:01Z"
}
```

### Evidence entry (`evidence/<target>/<timestamp>.json`)
```json
{
  "id": "evidence_20261031_143002",
  "category": "evidence",
  "target": "10.0.0.5",
  "file": "screenshot_20261031_143002.png",
  "mime_type": "image/png",
  "size_bytes": 245760,
  "description": "Admin panel login page",
  "deposited_by": "agent-2",
  "deposited_at": "2026-10-31T14:30:02Z"
}
```

---

## Inter-Agent Knowledge Sharing Flow

1. **Agent A** runs `nmap` against `10.0.0.5`, finds port 22/SSH open → writes finding to vault + SQLite
2. **Agent B** queries vault for `target:10.0.0.5` → sees SSH finding → runs `hydra` against port 22
3. **Agent B** finds credentials → writes credential to vault + SQLite
4. **Agent C** queries vault for credentials → sees SSH creds → uses `netexec` to verify access

Agents discover each other's work via `vault_list` / `vault_search` without needing direct communication.

---

## Index File (`index.json`)

```json
{
  "updated_at": "2026-10-31T14:30:02Z",
  "entries": [
    {"id": "cred_...", "category": "credentials", "target": "10.0.0.5", "path": "vault/credentials/10.0.0.5/cred_...json"},
    {"id": "finding_...", "category": "findings", "target": "10.0.0.5", "path": "vault/findings/10.0.0.5/finding_...json"}
  ],
  "count": 150
}
```

Regenerated on each `vault_write` / `vault_delete`. `vault_search` queries this index first, then reads matching entries.

---

## Security Model (Plaintext + Filesystem Perms)

- No encryption at rest (user decision)
- Vault dir created with `0700` permissions (owner only)
- Files created with `0600` permissions
- Agents share the same OS user → plaintext is acceptable within a trusted agent environment
- Sensitive fields (passwords, hashes) are stored plaintext but file-permission protected

> ⚠️ **Note:** If the server is exposed to untrusted users, enable `MCP_API_TOKEN` auth and restrict filesystem access. The vault is designed for agent-to-agent sharing within a trusted deployment.

---

## Integration with Wrappers

Each wrapper, after successful execution:
1. Parses output → normalized findings
2. Writes findings to SQLite `findings` table
3. Deposits normalized JSON to `vault/findings/<target>/<timestamp>.json`
4. If credentials found → writes to SQLite `credentials` table + `vault/credentials/<target>/<timestamp>.json`
5. Returns MCP response with normalized output + vault paths
