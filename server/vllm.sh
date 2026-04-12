#!/usr/bin/env bash
# Start vLLM via Docker (alternative to docker compose).
# Requires: Docker + NVIDIA Container Toolkit
set -euo pipefail

# Load .env if present
if [ -f "$(dirname "$0")/../.env" ]; then
    set -a; source "$(dirname "$0")/../.env"; set +a
fi

MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-Coder-7B-Instruct}"
PORT="${VLLM_PORT:-8000}"
GPU_MEM="${GPU_MEMORY_UTIL:-0.90}"
MAX_LEN="${MAX_MODEL_LEN:-32768}"
EXTRA="${VLLM_EXTRA_ARGS:---trust-remote-code --enforce-eager --enable-auto-tool-choice --tool-call-parser hermes}"

HF_CACHE="${HF_HOME:-$HOME/.cache/huggingface}"
mkdir -p "$HF_CACHE"

echo "Starting vLLM  model=${MODEL}  port=${PORT}"
echo "Endpoint: http://127.0.0.1:${PORT}/v1/chat/completions"
echo ""

docker run --rm \
  --name vllm-server \
  --gpus all \
  --ipc=host \
  -p "127.0.0.1:${PORT}:8000" \
  -v "${HF_CACHE}:/root/.cache/huggingface" \
  ${HUGGING_FACE_HUB_TOKEN:+-e HUGGING_FACE_HUB_TOKEN="$HUGGING_FACE_HUB_TOKEN"} \
  vllm/vllm-openai:latest \
  --model "${MODEL}" \
  --port 8000 \
  --host 0.0.0.0 \
  --gpu-memory-utilization "${GPU_MEM}" \
  --max-model-len "${MAX_LEN}" \
  ${EXTRA}
