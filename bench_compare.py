#!/usr/bin/env python3
"""
bench_compare.py — cross-model benchmark: 35B vs 80B, each with and without RTK.

Stops the current vLLM container, starts the target model, waits for health,
runs bench.py A+B, then repeats for the second model. Results are linked in
the DB by a shared compare_id for cross-model display in bench_viewer.

Usage:
    python3 bench_compare.py
    python3 bench_compare.py "your task here"
    python3 bench_compare.py "your task here" --runs 3
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
BASE_URL   = "http://127.0.0.1:8000"
HEALTH_URL = f"{BASE_URL}/health"

# Model configs — order determines run sequence (35B first, cheaper/faster warmup)
MODEL_CONFIGS = [
    {
        "tag":              "35b",
        "model_name":       "Qwen/Qwen3.6-35B-A3B",
        "local_model_name": "Qwen/Qwen3.6-35B-A3B",
        "health_timeout":   300,
        "start_mode":       "compose",
        "vllm_extra_args":  (
            "--trust-remote-code --enforce-eager "
            "--enable-auto-tool-choice --tool-call-parser qwen3_xml "
            "--enable-prefix-caching"
        ),
    },
    {
        "tag":              "80b",
        "model_name":       "nvidia/Qwen3-Next-80B-A3B-Instruct-NVFP4",
        "local_model_name": "qwen3-next-80b",
        "health_timeout":   600,
        "start_mode":       "docker_run",
    },
]


def stop_servers() -> None:
    """Stop and remove all running vLLM containers (both compose and standalone)."""
    print("  [compare] Stopping vLLM servers...", flush=True)
    subprocess.run(["docker", "rm", "-f", "vllm-server"], capture_output=True)
    subprocess.run(
        ["docker", "compose", "down", "vllm"],
        capture_output=True, cwd=str(HERE),
    )
    time.sleep(3)


def start_35b(cfg: dict) -> None:
    """Start 35B via docker compose with model-specific env vars."""
    env = {
        **os.environ,
        "VLLM_MODEL":      cfg["model_name"],
        "VLLM_EXTRA_ARGS": cfg.get("vllm_extra_args", ""),
    }
    subprocess.run(
        ["docker", "compose", "up", "-d", "vllm"],
        env=env, cwd=str(HERE), check=True,
    )


def start_80b(cfg: dict) -> None:
    """Start 80B via docker run -d using the NVFP4 kernel image."""
    home = Path.home()
    subprocess.run([
        "docker", "run", "-d",
        "--name", "vllm-server",
        "--gpus", "all",
        "--ipc=host",
        "--security-opt", "seccomp=unconfined",
        "--ulimit", "memlock=-1",
        "--ulimit", "stack=67108864",
        "-p", "127.0.0.1:8000:8000",
        "-v", f"{home}/.cache/huggingface:/root/.cache/huggingface",
        "-v", f"{home}/.cache/vllm:/root/.cache/vllm",
        "-v", f"{home}/.cache/triton:/root/.cache/triton",
        "-v", (
            f"{home}/sglang/patches/nvfp4.py:"
            "/app/vllm/vllm/model_executor/layers/fused_moe/oracle/nvfp4.py:ro"
        ),
        "-e", f"MODEL={cfg['model_name']}",
        "-e", "PORT=8000",
        "-e", "HOST=0.0.0.0",
        "-e", "GPU_MEMORY_UTIL=0.88",
        "-e", "MAX_MODEL_LEN=32768",
        "-e", "MAX_NUM_SEQS=16",
        "-e", (
            "VLLM_EXTRA_ARGS=--trust-remote-code "
            "--served-model-name qwen3-next-80b "
            "--enforce-eager --enable-auto-tool-choice "
            "--tool-call-parser qwen3_xml"
        ),
        "avarok/dgx-vllm-nvfp4-kernel:v23", "serve",
    ], check=True)


def wait_for_health(timeout: int, tag: str) -> None:
    """Poll GET /health until 200 or timeout. Raises TimeoutError on failure."""
    print(f"  [compare] Waiting for {tag} server (up to {timeout}s)...", flush=True)
    deadline = time.time() + timeout
    dots = 0
    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["curl", "-sf", "--max-time", "4", HEALTH_URL],
                capture_output=True,
            )
            if result.returncode == 0:
                print(f"\n  [compare] {tag} server is healthy.", flush=True)
                return
        except Exception:
            pass
        time.sleep(5)
        dots += 1
        if dots % 6 == 0:
            elapsed = int(time.time() - (deadline - timeout))
            print(f"  [compare] Still waiting... {elapsed}s elapsed", flush=True)
    raise TimeoutError(f"{tag} server did not become healthy within {timeout}s")


def run_bench(task: str, tag: str, compare_id: str, runs: int = 1) -> None:
    """Invoke bench.py as a subprocess with model tag and compare_id."""
    print(f"\n  [compare] Running bench for {tag} (runs={runs})...", flush=True)
    subprocess.run(
        [
            sys.executable, str(HERE / "bench.py"),
            task, "--tag", tag, "--compare-id", compare_id,
            "--runs", str(runs),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-model benchmark: 35B vs 80B, each with/without RTK"
    )
    parser.add_argument("task", nargs="?", default=None, help="Task description")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of A/B pairs to average per model (passed to bench.py)")
    args = parser.parse_args()

    sys.path.insert(0, str(HERE))
    from bench import DEFAULT_TASK
    task = args.task or DEFAULT_TASK

    compare_id = "cmp_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    print("Cross-model benchmark: 35B vs 80B")
    print(f"Task:       {task[:80]}{'…' if len(task) > 80 else ''}")
    print(f"Compare ID: {compare_id}")
    print(f"Sequence:   35B (A+B)  →  80B (A+B)\n", flush=True)

    for cfg in MODEL_CONFIGS:
        tag = cfg["tag"]
        print(f"\n{'='*60}")
        print(f"  MODEL: {tag}  ({cfg['model_name']})")
        print(f"{'='*60}", flush=True)

        stop_servers()

        try:
            if cfg["start_mode"] == "compose":
                start_35b(cfg)
            elif cfg["start_mode"] == "docker_run":
                start_80b(cfg)
            else:
                raise ValueError(f"Unknown start_mode: {cfg['start_mode']!r}")

            wait_for_health(cfg["health_timeout"], tag)
            os.environ["LOCAL_MODEL_NAME"] = cfg["local_model_name"]
            os.environ["LOCAL_MODEL_URL"]  = f"{BASE_URL}/v1/chat/completions"
            run_bench(task, tag, compare_id, runs=args.runs)
        except Exception as exc:
            print(f"\n  [compare] ERROR during {tag} run: {exc}", flush=True)
            print(f"  [compare] Partial results may exist under compare_id={compare_id}", flush=True)
            stop_servers()
            raise

    stop_servers()
    print(f"\n{'='*60}")
    print(f"✓ Cross-model benchmark complete.")
    print(f"  Compare ID: {compare_id}")
    print(f"  Open bench_viewer → Model Comparison section to see results.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
