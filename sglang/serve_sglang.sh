#!/usr/bin/env bash
# Local LLM server for the hybrid agentic coding system
# Container: avarok/dgx-vllm-nvfp4-kernel:v23 (vLLM 0.16.0, CUDA 13.0, SM121 native)
# Model:     nvidia/Qwen3-Next-80B-A3B-Instruct-NVFP4 (already in ~/.cache/huggingface)
# Backend:   NVFP4 + VLLM_CUTLASS MoE (patched) + enforce-eager
# API:       OpenAI-compatible — http://127.0.0.1:8000/v1/chat/completions
set -euo pipefail

mkdir -p "$HOME/.cache/vllm/torch_compile_cache"
mkdir -p "$HOME/.cache/triton"

docker run --rm \
  --name vllm-server \
  --gpus all \
  --ipc=host \
  --security-opt seccomp=unconfined \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -p 127.0.0.1:8000:8000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  -v "$HOME/.cache/vllm:/root/.cache/vllm" \
  -v "$HOME/.cache/triton:/root/.cache/triton" \
  -v "$HOME/sglang/patches/nvfp4.py:/app/vllm/vllm/model_executor/layers/fused_moe/oracle/nvfp4.py:ro" \
  -e MODEL="/root/.cache/huggingface/hub/models--nvidia--Qwen3-Next-80B-A3B-Instruct-NVFP4/snapshots/8fb2682f136cf94d932a498f18cb1e428832a912" \
  -e PORT=8000 \
  -e HOST=0.0.0.0 \
  -e GPU_MEMORY_UTIL=0.88 \
  -e MAX_MODEL_LEN=32768 \
  -e MAX_NUM_SEQS=16 \
  -e VLLM_EXTRA_ARGS="--trust-remote-code --served-model-name qwen3-next-80b --enforce-eager --enable-auto-tool-choice --tool-call-parser qwen3_xml" \
  avarok/dgx-vllm-nvfp4-kernel:v23 serve
