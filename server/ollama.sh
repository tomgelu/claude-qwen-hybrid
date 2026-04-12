#!/usr/bin/env bash
# Start Ollama with settings tuned for the agentic tool-calling loop.
# Ollama exposes an OpenAI-compatible API at http://127.0.0.1:11434/v1
set -euo pipefail

# Load .env if present
if [ -f "$(dirname "$0")/../.env" ]; then
    set -a; source "$(dirname "$0")/../.env"; set +a
fi

MODEL="${LOCAL_MODEL_NAME:-qwen2.5-coder:7b}"
PORT="${OLLAMA_PORT:-11434}"

# Ensure parallel requests don't collide (1 request at a time for the agent loop)
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-1h}"

echo "Starting Ollama  model=${MODEL}  port=${PORT}"
echo "Endpoint: http://127.0.0.1:${PORT}/v1/chat/completions"
echo ""

# Pull model if not already downloaded
if ! ollama list | grep -q "^${MODEL}"; then
    echo "Pulling ${MODEL} ..."
    ollama pull "${MODEL}"
fi

# Start server in background if not already running
if ! pgrep -x ollama &>/dev/null; then
    OLLAMA_HOST="0.0.0.0:${PORT}" ollama serve &
    echo "Waiting for Ollama to start..."
    for i in $(seq 1 30); do
        curl -sf "http://127.0.0.1:${PORT}/api/tags" &>/dev/null && break
        sleep 1
    done
else
    echo "Ollama already running."
fi

echo ""
echo "Ready. Health check:"
curl -s "http://127.0.0.1:${PORT}/api/tags" | python3 -c \
    "import json,sys; m=[x['name'] for x in json.load(sys.stdin)['models']]; print('  Models:', ', '.join(m) if m else '(none pulled)')" 2>/dev/null || true
echo ""
echo "Set in .env:  LOCAL_MODEL_URL=http://127.0.0.1:${PORT}/v1/chat/completions"
