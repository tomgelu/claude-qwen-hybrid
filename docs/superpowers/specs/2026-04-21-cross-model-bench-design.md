# Cross-Model Benchmark Comparison Design

## Goal

Run a full 4-run benchmark (35B no-RTK, 35B RTK, 80B no-RTK, 80B RTK) with a single command, swapping vLLM Docker containers between models automatically. Results are stored in the existing DB and displayed as a 4-column comparison in bench_viewer.

## New file: `bench_compare.py`

Orchestrates the full cross-model run sequentially:

1. Generate a `compare_id` (timestamp, e.g. `cmp_20260421_213717`) shared across both model runs.
2. For each model in order (35B first, then 80B):
   a. Stop any running vllm container (`docker stop vllm-server 2>/dev/null; docker compose down vllm 2>/dev/null`)
   b. Start the model's container (see Model Configs below)
   c. Poll `http://localhost:8000/health` until ready — 5 min timeout for 35B, 10 min for 80B
   d. Run `bench.py <task> --tag <model-label> --compare-id <compare_id>` as a subprocess
3. Stop the final container when done.
4. Print a combined summary table.

### Model Configs

**35B** (`label: "35b"`)
- Start: `VLLM_MODEL=Qwen/Qwen3.6-35B-A3B VLLM_EXTRA_ARGS="--trust-remote-code --enforce-eager --enable-auto-tool-choice --tool-call-parser qwen3_xml --enable-prefix-caching" docker compose up -d vllm`
- Stop: `docker compose down vllm`
- Served model name: `Qwen/Qwen3.6-35B-A3B`
- Health timeout: 300s

**80B** (`label: "80b"`)
- Start: `docker run --rm --name vllm-server ...` using image `avarok/dgx-vllm-nvfp4-kernel:v23`, mounting `~/sglang/patches/nvfp4.py`, served as `qwen3-next-80b`
- Stop: `docker stop vllm-server`
- Health timeout: 600s

The full `docker run` args are taken verbatim from `sglang/serve_sglang.sh` (non-blocking: run with `-d` flag or via subprocess with `Popen`).

## Changes to `bench.py`

Add two optional CLI args:
- `--tag <str>` — model label stored in DB (e.g. `35b`, `80b`). Default: empty string.
- `--compare-id <str>` — links this run to a cross-model comparison set. Default: empty string.

DB schema: add `model_label TEXT` and `compare_id TEXT` columns to `bench_runs` table (via `ALTER TABLE IF NOT EXISTS` on startup — safe to run on existing DB).

No other changes to bench.py logic.

## Changes to `bench_viewer.py`

Add a new **"Model Comparison"** section above the existing "Bench Runs" section.

- Detects run groups by shared `compare_id` (non-empty).
- Displays a 4-column metrics table: `35B (no RTK) | 35B (RTK) | 80B (no RTK) | 80B (RTK)`.
- Columns use the same `ROWS` metric definitions already in the viewer.
- A plain-English verdict per dimension:
  - **Tokens**: which model uses fewer input tokens
  - **Speed**: which model has lower wall time
  - **Quality**: which model passes more tests
- Summary banner (same style as existing) shows overall winner.

If no `compare_id` runs exist, the section is hidden.

## Usage

```bash
python3 bench_compare.py "build a CLI todo app"
python3 bench_compare.py              # uses default fibonacci task
```

## Out of scope

- Parallel execution (GPU can only host one model at a time)
- Automatic model download (models must already be in HuggingFace cache)
- More than 2 models per comparison run
