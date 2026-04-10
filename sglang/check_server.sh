#!/usr/bin/env bash
# Verify the SGLang server is healthy and run a quick completion test
set -euo pipefail

BASE="http://127.0.0.1:8000"
MODEL="qwen3-next-80b"

echo "=== SGLang Health Check ==="
echo ""

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health" 2>/dev/null || echo "000")
if [ "$STATUS" = "200" ]; then
    echo "Health:  OK (HTTP 200)"
else
    echo "Health:  UNREACHABLE (HTTP $STATUS) — is the server running?"
    exit 1
fi

echo "Models:"
curl -s "$BASE/v1/models" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('data', []):
    print(f\"  - {m['id']}\")
"

echo ""
echo "Test completion:"
curl -s "$BASE/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{
        \"model\": \"$MODEL\",
        \"messages\": [{\"role\": \"user\", \"content\": \"Write a Python one-liner to check if a number is prime.\"}],
        \"max_tokens\": 100,
        \"temperature\": 0
    }" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data['choices'][0]['message']['content'])
"
