#!/usr/bin/env bash
# SGLang setup for NVIDIA GB10 (DGX Spark) — aarch64, CUDA 13.0
# Model: Qwen/Qwen2.5-Coder-32B-Instruct (BF16, 130GB unified memory)
# Run this only if starting from scratch — setup has already been done if
# ~/sglang/venv exists and ~/sglang/models/Qwen2.5-Coder-32B-Instruct is populated.
set -euo pipefail

VENV="$HOME/sglang/venv"
MODEL_DIR="$HOME/sglang/models/Qwen2.5-Coder-32B-Instruct"

echo "=== SGLang Setup for DGX Spark GB10 ==="
echo ""

# ── 1. Create virtualenv ──────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
    echo "[1/4] Creating virtualenv at $VENV ..."
    mkdir -p "$HOME/sglang"
    python3 -m venv "$VENV"
else
    echo "[1/4] Virtualenv already exists at $VENV"
fi

source "$VENV/bin/activate"

# ── 2. Install PyTorch & SGLang ───────────────────────────────────────────────
echo "[2/4] Installing torch==2.11.0 and sglang[all]==0.5.10 ..."
pip install --upgrade pip --quiet
pip install "sglang[all]==0.5.10" --quiet
# Force CUDA-enabled torch after sglang deps may downgrade it
pip install "torch==2.11.0" --force-reinstall --quiet

echo "      torch:      $(python -c 'import torch; print(torch.__version__)')"
echo "      sglang:     $(python -c 'import sglang; print(sglang.__version__)')"
echo "      flashinfer: $(python -c 'import flashinfer; print(flashinfer.__version__)')"
echo "      CUDA:       $(python -c 'import torch; print(torch.cuda.is_available())')"

# ── 3. Download model ─────────────────────────────────────────────────────────
if [ -d "$MODEL_DIR" ] && [ "$(ls -A "$MODEL_DIR")" ]; then
    echo "[3/4] Model already downloaded at $MODEL_DIR"
else
    echo "[3/4] Downloading Qwen2.5-Coder-32B-Instruct (~64GB BF16) ..."
    mkdir -p "$MODEL_DIR"
    python - <<'PYEOF'
from huggingface_hub import snapshot_download
import os
path = snapshot_download(
    repo_id="Qwen/Qwen2.5-Coder-32B-Instruct",
    local_dir=os.path.expanduser("~/sglang/models/Qwen2.5-Coder-32B-Instruct"),
)
print("Download complete:", path)
PYEOF
fi

# ── 4. Install systemd service ────────────────────────────────────────────────
echo "[4/4] Installing systemd service (requires sudo) ..."
sudo cp "$HOME/sglang/sglang.service" /etc/systemd/system/sglang.service
sudo systemctl daemon-reload
sudo systemctl enable sglang.service

echo ""
echo "=== Setup complete ==="
echo "Start:  sudo systemctl start sglang"
echo "Logs:   sudo journalctl -u sglang -f"
echo "Check:  bash $(dirname "$0")/check_server.sh"
