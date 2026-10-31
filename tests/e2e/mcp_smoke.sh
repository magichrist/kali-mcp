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

parse_result() {
    python3 -c "
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
" 2>/dev/null || echo "PARSE_ERROR"
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

# ── Verify all 30 tools present ────────────────────────────────────────
log "Checking all tools are registered..."

echo "$TOOLS_DATA" | python3 -c "
import sys, json
d = json.load(sys.stdin)
tools = d.get('result',{}).get('tools',[])
names = {t['name'] for t in tools}
expected = [
    'generic_command','python_command','file_read','file_write',
    'nmap','httpx','nuclei','ffuf','katana','subfinder','amass',
    'sqlmap','commix','wpscan','enum4linux','netexec','crackmapexec',
    'bloodhound','theharvester','spiderfoot','naabu','arjun','whatweb',
    'searchsploit','dursgo','farsight','flowlyt',
    'zighound','zizmor','file_download'
]
missing = [n for n in expected if n not in names]
if missing:
    print(f'MISSING:{",".join(missing)}')
else:
    print(f'OK:{len(expected)}')
" > "$TMPDIR/tools_check" 2>/dev/null

TOOLS_CHECK=$(cat "$TMPDIR/tools_check")
if echo "$TOOLS_CHECK" | grep -q "^OK:"; then
    ok "All tools registered ($(echo "$TOOLS_CHECK" | cut -d: -f2) tools)"
else
    err "Missing tools: $(echo "$TOOLS_CHECK" | cut -d: -f2)"
fi

# ── Step 3: Call httpx ──────────────────────────────────────────────────
log "Calling httpx (target=http://example.com)..."

mcp_post "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"httpx\",\"arguments\":{\"target\":\"http://example.com\",\"extra_args\":\"-status-code -title -tech-detect\"}}}" \
    "$TMPDIR/httpx_body" "$TMPDIR/httpx_hdrs" \
    "Mcp-Session-Id: $SESSION"

HTTPX_DATA=$(extract_data "$TMPDIR/httpx_body")
HTTPX_RESULT=$(echo "$HTTPX_DATA" | parse_result)
HTTPX_STATUS=$(echo "$HTTPX_RESULT" | head -1)
HTTPX_BODY=$(echo "$HTTPX_RESULT" | tail -n +2)

if [ "$HTTPX_STATUS" = "OK" ]; then
    if echo "$HTTPX_BODY" | grep -qi "example.com\|200\|301"; then
        ok "httpx probed example.com"
    else
        ok "httpx executed successfully"
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
NMAP_RESULT=$(echo "$NMAP_DATA" | parse_result)
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
PY_RESULT=$(echo "$PY_DATA" | parse_result)
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
WRITE_RESULT=$(echo "$WRITE_DATA" | parse_result)
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
READ_RESULT=$(echo "$READ_DATA" | parse_result)
READ_STATUS=$(echo "$READ_RESULT" | head -1)
READ_BODY=$(echo "$READ_RESULT" | tail -n +2)

if [ "$READ_STATUS" = "OK" ] && echo "$READ_BODY" | grep -q "hello from mcp"; then
    ok "file_read got content back"
else
    err "file_read failed"
    echo "  $READ_BODY" | head -2
fi

# ── Step 8: health_check (HTTP endpoint) ───────────────────────────────
log "Calling health_check..."

HEALTH_URL=$(echo "$URL" | sed 's|/mcp$||')
HEALTH_HTTP=$(curl -sf --max-time 5 "${HEALTH_URL}/health" 2>/dev/null || echo "CURL_FAIL")

if echo "$HEALTH_HTTP" | grep -q "healthy"; then
    ok "health_check reports status=healthy"
else
    err "health_check failed"
    echo "  $HEALTH_HTTP" | head -3
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
