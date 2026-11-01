# Kali MCP Server — Result Normalization Plan (Per-Tool)

**Goal:** Convert raw tool output into structured, per-tool JSON schemas that AI agents can consume without parsing unstructured text.

**Priority:** P0  
**Scope:** Per-tool normalization (each tool gets its own schema) — NOT a single unified cross-tool schema.  
**Approach:** Hybrid — normalization layer built in parallel with wrappers; every new wrapper emits normalized output.

---

## Design

### Normalization Mixin

A `NormalizedToolMixin` provides shared helpers:

```python
class NormalizedToolMixin:
    def normalize(
        self, raw_stdout: str, raw_stderr: str, exit_code: int
    ) -> dict[str, Any]:
        """Subclasses implement per-tool parsing."""
        raise NotImplementedError
```

Each wrapper calls its `normalize()` inside `execute()` and merges the normalized dict into the `ExecutionResult.stdout` as structured JSON (not double-encoded — see BUG-012 fix).

### Output Contract

Every tool's `ExecutionResult.stdout` contains:

```json
{
  "raw": "<original tool stdout>",
  "normalized": { ...per-tool fields... },
  "parsed_at": "<ISO timestamp>",
  "parse_success": true/false,
  "parse_error": "<error if parsing failed>"
}
```

If parsing fails, `parse_success: false` and `normalized: {}` — the agent still gets raw output.

---

## Per-Tool Normalized Schemas

### nmap
```json
{
  "target": "10.0.0.1",
  "hosts_up": 1,
  "ports": [
    {"port": 80, "protocol": "tcp", "state": "open", "service": "http", "version": "Apache 2.4.41"},
    {"port": 443, "protocol": "tcp", "state": "open", "service": "https", "version": "nginx 1.18"}
  ],
  "os_guess": "Linux 3.x-4.x",
  "scan_time": "45.2s"
}
```

### nuclei
```json
{
  "target": "https://example.com",
  "templates_loaded": 1250,
  "findings": [
    {"template_id": "cve-2021-44228", "name": "Log4Shell", "severity": "critical", "url": "...", "matched_at": "..."}
  ],
  "severity_counts": {"critical": 2, "high": 5, "medium": 10, "low": 3, "info": 50}
}
```

### sqlmap
```json
{
  "target": "https://example.com/page?id=1",
  "vulnerable": true,
  "injection_points": [
    {"parameter": "id", "type": "Boolean-based blind", "dbms": "MySQL", "payload": "..."}
  ],
  "databases": ["users", "products"],
  "tables": 8
}
```

### msfconsole
```json
{
  "module": "exploit/multi/handler",
  "payload": "cmd/unix/reverse",
  "target": "10.0.0.1:4444",
  "session_opened": true,
  "session_id": 1,
  "shell_output": "..."
}
```

### hydra
```json
{
  "target": "10.0.0.1",
  "service": "ssh",
  "port": 22,
  "credentials_found": [
    {"username": "admin", "password": "password123"}
  ],
  "total_attempts": 500
}
```

### hashcat / john
```json
{
  "hash_type": "NTLM",
  "cracked": [
    {"hash": "31d6cfe0d16ae931b73c59d7e0c089c0", "plaintext": "password123"}
  ],
  "total_cracked": 1,
  "runtime": "120.5s"
}
```

### gobuster / dirb / wfuzz
```json
{
  "url": "https://example.com",
  "hits": [
    {"path": "/admin", "status_code": 200, "size": "4512"},
    {"path": "/api", "status_code": 403, "size": "128"}
  ],
  "total_found": 2
}
```

### masscan / naabu / nmap (port-focused)
```json
{
  "target": "10.0.0.0/24",
  "hosts_up": 3,
  "open_ports": [
    {"ip": "10.0.0.5", "port": 80, "protocol": "tcp"},
    {"ip": "10.0.0.10", "port": 443, "protocol": "tcp"}
  ]
}
```

### bettercap / responder
```json
{
  "module": "arp.spoof",
  "packets_captured": 15420,
  "hosts_discovered": 12,
  "credentials_sniffed": [
    {"username": "admin", "hash": "ntlmv2_hash...", "source_ip": "10.0.0.5"}
  ]
}
```

### zap / owasp-zap
```json
{
  "target": "https://example.com",
  "alerts": [
    {"name": "XSS", "risk": "high", "url": "...", "parameter": "q", "evidence": "<script>..."}
  ],
  "risk_counts": {"high": 3, "medium": 7, "low": 12, "informational": 45}
}
```

---

## Integration with SQLite + Vault

Every wrapper that produces findings:
1. Writes normalized findings to SQLite `findings` table (target, tool, finding_type, severity, evidence, timestamp)
2. Deposits a summary into the plaintext vault (`vault/findings/<target>/<timestamp>.json`)
3. Returns normalized output in MCP response

See `docs/target-scope-management-plan.md` and `docs/credential-evidence-vault-plan.md`.

---

## Backward Compatibility

Existing 30 tools keep their current behavior (raw output in stdout). Normalization is opt-in per tool. New wrappers ship with normalization from day one.
