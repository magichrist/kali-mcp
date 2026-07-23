#!/usr/bin/env bash

if [ $# -ne 1 ]; then
    echo "Usage: $0 <mcp-url>"
    echo "Example: $0 http://192.168.2.4:8399/mcp"
    exit 1
fi

URL="$1"
PASS=0
FAIL=0
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

log() { echo -e "\033[1;34m[*]\033[0m $1"; }
ok()  { echo -e "\033[1;32m[PASS]\033[0m $1"; ((PASS++)); }
err() { echo -e "\033[1;31m[FAIL]\033[0m $1"; ((FAIL++)); }

# POST to MCP, write body to file, dump headers to separate file
mcp_post() {
    local payload="$1"
    local body_file="$2"
    local header_file="$3"
    shift 3
    local curl_args=(
        --max-time 15
        -X POST "$URL"
        -H "Content-Type: application/json"
        -H "Accept: application/json, text/event-stream"
    )
    if [ $# -gt 0 ]; then
        for h in "$@"; do
            curl_args+=(-H "$h")
        done
    fi
    curl_args+=(-D "$header_file" -o "$body_file" -d "$payload")
    curl -sf "${curl_args[@]}" 2>/dev/null || true
}

extract_data() {
    grep '^data:' "$1" 2>/dev/null | head -1 | sed 's/^data: //'
}

get_session() {
    grep -i 'mcp-session-id' "$1" 2>/dev/null | awk '{print $2}' | tr -d '\r\n'
}

# ── Step 1: Initialize ──────────────────────────────────────────────────
log "Initializing MCP session..."

mcp_post '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0"}}}' \
    "$TMPDIR/init_body" "$TMPDIR/init_hdrs"

SESSION=$(get_session "$TMPDIR/init_hdrs")

if [ -z "$SESSION" ]; then
    err "Failed to get session ID"
    cat "$TMPDIR/init_hdrs" "$TMPDIR/init_body" 2>/dev/null | head -10
    exit 1
fi
ok "Got session: $SESSION"

# Send initialized notification
mcp_post '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    "$TMPDIR/notif_body" "$TMPDIR/notif_hdrs" \
    "Mcp-Session-Id: $SESSION"

# ── Step 2: tools/list ─────────────────────────────────────────────────
log "Checking tools/list has input schemas..."

mcp_post '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
    "$TMPDIR/tools_body" "$TMPDIR/tools_hdrs" \
    "Mcp-Session-Id: $SESSION"

TOOLS_DATA=$(extract_data "$TMPDIR/tools_body")

TOOL_COUNT=$(echo "$TOOLS_DATA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(len(d.get('result',{}).get('tools',[])))
" 2>/dev/null || echo "0")

if [ "$TOOL_COUNT" -ge 20 ]; then
    ok "tools/list returned $TOOL_COUNT tools"
else
    err "tools/list returned only $TOOL_COUNT tools (expected >=20)"
fi

HAS_SCHEMA=$(echo "$TOOLS_DATA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
tools = d.get('result',{}).get('tools',[])
# Tools with required params should have non-empty properties
bad = [t['name'] for t in tools
       if t.get('inputSchema',{}).get('required')
       and not t.get('inputSchema',{}).get('properties')]
print(len(bad))
if bad:
    for b in bad:
        print(f'  Missing: {b}', file=sys.stderr)
" 2>/dev/null || echo "?")

if [ "$HAS_SCHEMA" = "0" ]; then
    ok "All tools have input schemas with properties"
else
    err "$HAS_SCHEMA tool(s) missing input schemas"
fi

# ── Step 3: Call httpx ──────────────────────────────────────────────────
log "Calling httpx (target=http://example.com)..."

mcp_post "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"httpx\",\"arguments\":{\"target\":\"http://example.com\",\"extra_args\":\"-status-code -title -tech-detect\"}}}" \
    "$TMPDIR/httpx_body" "$TMPDIR/httpx_hdrs" \
    "Mcp-Session-Id: $SESSION"

HTTPX_DATA=$(extract_data "$TMPDIR/httpx_body")

HTTPX_RESULT=$(echo "$HTTPX_DATA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:300])
" 2>/dev/null || echo "PARSE_ERROR")

HTTPX_STATUS=$(echo "$HTTPX_RESULT" | head -1)
HTTPX_BODY=$(echo "$HTTPX_RESULT" | tail -n +2)

if [ "$HTTPX_STATUS" = "OK" ]; then
    if echo "$HTTPX_BODY" | grep -qi "example.com\|200\|301"; then
        ok "httpx probed example.com — got status/title"
    else
        ok "httpx executed successfully (no validation error)"
    fi
else
    err "httpx returned error"
    echo "  $HTTPX_BODY" | head -2
fi

# ── Step 4: Call nmap ───────────────────────────────────────────────────
log "Calling nmap (target=127.0.0.1, ports=22)..."

mcp_post "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"nmap\",\"arguments\":{\"target\":\"127.0.0.1\",\"scan_type\":\"-sT\",\"ports\":\"22\"}}}" \
    "$TMPDIR/nmap_body" "$TMPDIR/nmap_hdrs" \
    "Mcp-Session-Id: $SESSION"

NMAP_DATA=$(extract_data "$TMPDIR/nmap_body")

NMAP_RESULT=$(echo "$NMAP_DATA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:300])
" 2>/dev/null || echo "PARSE_ERROR")

NMAP_STATUS=$(echo "$NMAP_RESULT" | head -1)
NMAP_BODY=$(echo "$NMAP_RESULT" | tail -n +2)

if [ "$NMAP_STATUS" = "OK" ]; then
    ok "nmap completed on 127.0.0.1:22"
else
    err "nmap returned error"
    echo "  $NMAP_BODY" | head -2
fi

# ── Step 5: Call python_command ──────────────────────────────────────────
log "Calling python_command..."

mcp_post '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"python_command","arguments":{"code":"import sys; print(f\"Python {sys.version_info.major}.{sys.version_info.minor}\"); print(sum(range(100)))"}}}' \
    "$TMPDIR/py_body" "$TMPDIR/py_hdrs" \
    "Mcp-Session-Id: $SESSION"

PY_DATA=$(extract_data "$TMPDIR/py_body")

PY_RESULT=$(echo "$PY_DATA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:300])
" 2>/dev/null || echo "PARSE_ERROR")

PY_STATUS=$(echo "$PY_RESULT" | head -1)
PY_BODY=$(echo "$PY_RESULT" | tail -n +2)

if [ "$PY_STATUS" = "OK" ] && echo "$PY_BODY" | grep -q "4950"; then
    ok "python_command executed — sum(0..99)=4950"
else
    err "python_command returned error"
    echo "  $PY_BODY" | head -2
fi

# ── Step 6: Call file_write ──────────────────────────────────────────────
log "Calling file_write (create /tmp/mcp_test.txt)..."

mcp_post "{\"jsonrpc\":\"2.0\",\"id\":6,\"method\":\"tools/call\",\"params\":{\"name\":\"file_write\",\"arguments\":{\"path\":\"/tmp/mcp_test.txt\",\"content\":\"hello from mcp\\nline 2\\n\"}}}" \
    "$TMPDIR/write_body" "$TMPDIR/write_hdrs" \
    "Mcp-Session-Id: $SESSION"

WRITE_DATA=$(extract_data "$TMPDIR/write_body")

WRITE_RESULT=$(echo "$WRITE_DATA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:300])
" 2>/dev/null || echo "PARSE_ERROR")

WRITE_STATUS=$(echo "$WRITE_RESULT" | head -1)
WRITE_BODY=$(echo "$WRITE_RESULT" | tail -n +2)

if [ "$WRITE_STATUS" = "OK" ] && echo "$WRITE_BODY" | grep -q "bytes_written"; then
    ok "file_write created /tmp/mcp_test.txt"
else
    err "file_write failed"
    echo "  $WRITE_BODY" | head -2
fi

# ── Step 7: Call file_read ───────────────────────────────────────────────
log "Calling file_read (/tmp/mcp_test.txt)..."

mcp_post '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"file_read","arguments":{"path":"/tmp/mcp_test.txt"}}}' \
    "$TMPDIR/read_body" "$TMPDIR/read_hdrs" \
    "Mcp-Session-Id: $SESSION"

READ_DATA=$(extract_data "$TMPDIR/read_body")

READ_RESULT=$(echo "$READ_DATA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:300])
" 2>/dev/null || echo "PARSE_ERROR")

READ_STATUS=$(echo "$READ_RESULT" | head -1)
READ_BODY=$(echo "$READ_RESULT" | tail -n +2)

if [ "$READ_STATUS" = "OK" ] && echo "$READ_BODY" | grep -q "hello from mcp"; then
    ok "file_read got content back"
else
    err "file_read failed"
    echo "  $READ_BODY" | head -2
fi

# ── Step 8: health_check ────────────────────────────────────────────────
log "Calling health_check..."

mcp_post '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"health_check","arguments":{}}}' \
    "$TMPDIR/health_body" "$TMPDIR/health_hdrs" \
    "Mcp-Session-Id: $SESSION"

HEALTH_DATA=$(extract_data "$TMPDIR/health_body")

HEALTH_RESULT=$(echo "$HEALTH_DATA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:400])
" 2>/dev/null || echo "PARSE_ERROR")

HEALTH_STATUS=$(echo "$HEALTH_RESULT" | head -1)
HEALTH_BODY=$(echo "$HEALTH_RESULT" | tail -n +2)

if [ "$HEALTH_STATUS" = "OK" ] && echo "$HEALTH_BODY" | grep -q "healthy"; then
    ok "health_check reports status=healthy"
else
    err "health_check failed"
    echo "  $HEALTH_BODY" | head -3
fi

# ── dursgo validation ─────────────────────────────────────────────────
log "Testing dursgo (validation check)"
DURSGO_RESULT=$(mcp_post '{"jsonrpc":"2.0","id":30,"method":"tools/call","params":{"name":"dursgo","arguments":{}}}' /dev/stdout)
DURSGO_STATUS=$(echo "$DURSGO_RESULT" | head -1)
DURSGO_BODY=$(echo "$DURSGO_RESULT" | tail -n +2)
DURSGO_CHECK=$(echo "$DURSGO_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:400])
" 2>/dev/null || echo "PARSE_ERROR")

DURSGO_STATUS_LINE=$(echo "$DURSGO_CHECK" | head -1)
DURSGO_BODY_LINE=$(echo "$DURSGO_CHECK" | tail -n +2)

if [ "$DURSGO_STATUS_LINE" = "ERROR" ] && echo "$DURSGO_BODY_LINE" | grep -q "target"; then
    ok "dursgo rejects missing target"
else
    err "dursgo validation failed"
    echo "  $DURSGO_BODY_LINE" | head -3
fi

# ── zighound validation ───────────────────────────────────────────────
log "Testing zighound (validation check)"
ZH_RESULT=$(mcp_post '{"jsonrpc":"2.0","id":31,"method":"tools/call","params":{"name":"zighound","arguments":{}}}' /dev/stdout)
ZH_STATUS=$(echo "$ZH_RESULT" | head -1)
ZH_BODY=$(echo "$ZH_RESULT" | tail -n +2)
ZH_CHECK=$(echo "$ZH_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:400])
" 2>/dev/null || echo "PARSE_ERROR")

ZH_STATUS_LINE=$(echo "$ZH_CHECK" | head -1)
ZH_BODY_LINE=$(echo "$ZH_CHECK" | tail -n +2)

if [ "$ZH_STATUS_LINE" = "ERROR" ] && echo "$ZH_BODY_LINE" | grep -q "command"; then
    ok "zighound rejects missing command"
else
    err "zighound validation failed"
    echo "  $ZH_BODY_LINE" | head -3
fi

# ── searchsploit validation ──────────────────────────────────────────
log "Testing searchsploit (validation check)"
SS_RESULT=$(mcp_post '{"jsonrpc":"2.0","id":32,"method":"tools/call","params":{"name":"searchsploit","arguments":{}}}' /dev/stdout)
SS_STATUS=$(echo "$SS_RESULT" | head -1)
SS_BODY=$(echo "$SS_RESULT" | tail -n +2)
SS_CHECK=$(echo "$SS_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:400])
" 2>/dev/null || echo "PARSE_ERROR")

SS_STATUS_LINE=$(echo "$SS_CHECK" | head -1)
SS_BODY_LINE=$(echo "$SS_CHECK" | tail -n +2)

if [ "$SS_STATUS_LINE" = "ERROR" ] && echo "$SS_BODY_LINE" | grep -q "query\|cve\|edb"; then
    ok "searchsploit rejects missing query/cve/edb_id"
else
    err "searchsploit validation failed"
    echo "  $SS_BODY_LINE" | head -3
fi

# ── farsight validation ──────────────────────────────────────────────
log "Testing farsight (validation check)"
FS_RESULT=$(mcp_post '{"jsonrpc":"2.0","id":33,"method":"tools/call","params":{"name":"farsight","arguments":{}}}' /dev/stdout)
FS_STATUS=$(echo "$FS_RESULT" | head -1)
FS_BODY=$(echo "$FS_RESULT" | tail -n +2)
FS_CHECK=$(echo "$FS_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:400])
" 2>/dev/null || echo "PARSE_ERROR")

FS_STATUS_LINE=$(echo "$FS_CHECK" | head -1)
FS_BODY_LINE=$(echo "$FS_CHECK" | tail -n +2)

if [ "$FS_STATUS_LINE" = "ERROR" ] && echo "$FS_BODY_LINE" | grep -q "domain"; then
    ok "farsight rejects missing domain"
else
    err "farsight validation failed"
    echo "  $FS_BODY_LINE" | head -3
fi

# ── flowlyt validation ───────────────────────────────────────────────
log "Testing flowlyt (validation check)"
FL_RESULT=$(mcp_post '{"jsonrpc":"2.0","id":34,"method":"tools/call","params":{"name":"flowlyt","arguments":{}}}' /dev/stdout)
FL_STATUS=$(echo "$FL_RESULT" | head -1)
FL_BODY=$(echo "$FL_RESULT" | tail -n +2)
FL_CHECK=$(echo "$FL_BODY" | python3 -c "
import sys,json
d=json.load(sys.stdin)
result = d.get('result',{})
is_err = result.get('isError', False)
text = ''
for c in result.get('content',[]):
    if c.get('type') == 'text':
        text = c['text']
        break
print('ERROR' if is_err else 'OK')
print(text[:400])
" 2>/dev/null || echo "PARSE_ERROR")

FL_STATUS_LINE=$(echo "$FL_CHECK" | head -1)
FL_BODY_LINE=$(echo "$FL_CHECK" | tail -n +2)

if [ "$FL_STATUS_LINE" = "ERROR" ] && echo "$FL_BODY_LINE" | grep -q "repo"; then
    ok "flowlyt rejects missing repo"
else
    err "flowlyt validation failed"
    echo "  $FL_BODY_LINE" | head -3
fi

# ── Summary ─────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
TOTAL=$((PASS + FAIL))
if [ "$FAIL" -eq 0 ]; then
    echo -e "\033[1;32mAll $TOTAL tests passed\033[0m"
else
    echo -e "\033[1;31m$FAIL/$TOTAL tests failed\033[0m"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exit $FAIL
