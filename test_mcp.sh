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

# ── Step 5: health_check ────────────────────────────────────────────────
log "Calling health_check..."

mcp_post '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"health_check","arguments":{}}}' \
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
