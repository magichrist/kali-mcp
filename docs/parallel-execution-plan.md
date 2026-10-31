# Kali MCP Server — Parallel Execution & Fan-Out Plan

**Goal:** Run multiple independent Kali tools concurrently against a target and aggregate results — faster recon, better throughput for AI agents.

**Priority:** P1  
**Approach:** Hybrid — built on top of existing execution engine semaphore (Phase 4)

---

## Design

### Fan-Out Tool

**Tool:** `parallel_execute`  
**Purpose:** Run a list of tool calls concurrently against the same target, aggregate + deduplicate results.

**Params:**
- `target` — the target (IP, hostname, URL)
- `tools` — list of tool specs: `[{"tool": "nmap", "args": {...}}, {"tool": "naabu", "args": {...}}, ...]`
- `max_concurrent` — max parallel sub-executions (default: engine max_concurrent)
- `aggregate` — whether to deduplicate and merge results (default: true)

**Returns:** Combined results per sub-tool + aggregated summary (unique open ports, unique vulnerabilities, unique credentials).

---

## Execution Model

```
Client → parallel_execute
  → Fan-out: N sub-executions concurrently (bounded by semaphore)
  → Each sub-tool runs via existing engine.execute()
  → Results collected as they complete
  → Aggregation: deduplicate by (target, port, service) / (target, template_id) / etc.
  → Return: per-tool results + aggregated findings
```

### Concurrency Control

- Reuses `engine._semaphore` (global max_concurrent) — no new semaphore needed
- Each sub-execution gets its own `request_id`
- Progress callback reports per-sub-tool progress (0-100%)
- Timeout per sub-tool (inherits from tool's default_timeout or per-call override)

---

## Aggregation Rules

| Finding Type | Dedup Key | Merge Strategy |
|--------------|-----------|----------------|
| Open port | (target, port, protocol) | Keep highest-severity service info |
| Vulnerability | (target, template_id) | Keep first occurrence, merge evidence |
| Credential | (target, service, username) | Keep most recent password/hash |
| Directory | (target, url_path) | Keep first status code/size |

---

## Example Use Cases

**Recon fan-out against a single host:**
```json
{
  "target": "10.0.0.5",
  "tools": [
    {"tool": "nmap", "args": {"scan_type": "-sV", "ports": "1-1000"}},
    {"tool": "naabu", "args": {}},
    {"tool": "whatweb", "args": {"target": "http://10.0.0.5"}},
    {"tool": "httpx", "args": {"target": "http://10.0.0.5"}}
  ]
}
```

**Returns:** Aggregated open ports, services, technologies, live URLs — deduplicated.

---

## Integration with Playbooks

Playbooks use `parallel_execute` for independent phases (e.g., Phase 1 of recon: subfinder + httpx + masscan + whatweb all at once), then sequential phases for dependent tools (nmap needs hosts from httpx first).

---

## MCP Tools

| Tool | Purpose | Params |
|------|---------|--------|
| `parallel_execute` | Run multiple tools concurrently, aggregate results | target, tools, max_concurrent, aggregate |
| `parallel_status` | Check status of a fan-out run | run_id |

---

## Testing

- Concurrent execution of 3+ mock tools returns all results
- Aggregation deduplicates overlapping findings
- Timeout on one sub-tool doesn't cancel others
- Progress callback fires for each sub-tool
