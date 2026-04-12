#!/usr/bin/env bash
# Health check + smoke test for any OpenAI-compatible local model server.
set -euo pipefail

# Load .env if present
if [ -f "$(dirname "$0")/../.env" ]; then
    set -a; source "$(dirname "$0")/../.env"; set +a
fi

BASE_URL="${LOCAL_MODEL_URL:-http://127.0.0.1:8000/v1/chat/completions}"
# Strip path to get base (works for both /v1/chat/completions and bare host)
HOST_URL=$(echo "$BASE_URL" | sed 's|/v1/.*||')
MODEL="${LOCAL_MODEL_NAME:-qwen2.5-coder:7b}"

echo "Checking ${HOST_URL} ..."
echo ""

# 1. Health endpoint
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${HOST_URL}/health" 2>/dev/null || echo "000")
if [ "$HTTP" = "200" ]; then
    echo "  /health       OK (200)"
else
    echo "  /health       ${HTTP} — server may not be running"
    exit 1
fi

# 2. Models list
MODELS=$(curl -s "${HOST_URL}/v1/models" 2>/dev/null | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(', '.join(m['id'] for m in d.get('data', [])))" 2>/dev/null || echo "(unavailable)")
echo "  /v1/models    ${MODELS}"

# 3. Simple chat completion
echo "  chat/completions ..."
RESPONSE=$(curl -s "${BASE_URL}" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"${MODEL}\",
    \"messages\": [{\"role\": \"user\", \"content\": \"Reply with exactly: ok\"}],
    \"max_tokens\": 8,
    \"temperature\": 0
  }" 2>/dev/null)

CONTENT=$(echo "$RESPONSE" | python3 -c \
    "import json,sys; print(json.load(sys.stdin)['choices'][0]['message']['content'].strip())" 2>/dev/null || echo "(parse error)")

echo "  response:     '${CONTENT}'"
echo ""

if echo "$CONTENT" | grep -qi "ok"; then
    echo "Server is ready."
else
    echo "Server responded but output looks unexpected — check model name."
fi
