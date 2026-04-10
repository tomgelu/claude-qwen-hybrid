# Hybrid Agentic Coding System

Claude Code (cloud) as **Planner** — local Qwen model on DGX Spark as **Executor**.

Claude breaks the goal into a structured JSON plan. Qwen executes each step autonomously using real tools: reading files, writing code, running commands, verifying output.

```
You
 └─▶ Claude Code (Planner)        — cloud, your subscription, no API key
        └─▶ JSON Plan
               └─▶ Qwen3-Next-80B (Executor)   — local, DGX Spark, port 8000
                      └─▶ Tools: read_file · write_file · run_command · git
                             └─▶ Working code
```

---

## Prerequisites

- NVIDIA DGX Spark (GB10, SM12.1, 128 GB unified memory)
- Docker with GPU access
- Claude Code CLI installed (`claude --version`)
- Python 3.10+

---

## 1. One-time setup

### 1.1 Clone this repo

```bash
git clone <this-repo> ~/claude-autonaumous
cd ~/claude-autonaumous
pip install requests mcp --break-system-packages
```

### 1.2 Download the model (already done if on the DGX Spark)

The model `nvidia/Qwen3-Next-80B-A3B-Instruct-NVFP4` is stored at:
```
~/.cache/huggingface/hub/models--nvidia--Qwen3-Next-80B-A3B-Instruct-NVFP4/
```

If you need to download it:
```bash
pip install huggingface_hub --break-system-packages
huggingface-cli download nvidia/Qwen3-Next-80B-A3B-Instruct-NVFP4
```

### 1.3 Apply the SM12.1 patch

The container needs one patched file to skip FlashInfer JIT (which fails on SM12.1):

```bash
mkdir -p ~/sglang/patches
docker run --rm avarok/dgx-vllm-nvfp4-kernel:v23 \
  cat /app/vllm/vllm/model_executor/layers/fused_moe/oracle/nvfp4.py \
  > ~/sglang/patches/nvfp4.py
```

Then edit `~/sglang/patches/nvfp4.py` — find the `select_nvfp4_moe_backend()` function and replace the `AVAILABLE_BACKENDS` assignment with:

```python
import os, torch
_cc = torch.cuda.get_device_capability()
if _cc == (12, 1):
    AVAILABLE_BACKENDS = [NvFp4MoeBackend.VLLM_CUTLASS, NvFp4MoeBackend.MARLIN]
else:
    AVAILABLE_BACKENDS = [
        NvFp4MoeBackend.FLASHINFER_TRTLLM, NvFp4MoeBackend.FLASHINFER_CUTEDSL,
        NvFp4MoeBackend.FLASHINFER_CUTLASS, NvFp4MoeBackend.VLLM_CUTLASS,
        NvFp4MoeBackend.MARLIN,
    ]
```

### 1.4 Add the `qwen` alias

```bash
echo "alias qwen='python3 $HOME/claude-autonaumous/qwen_cli.py'" >> ~/.bashrc
source ~/.bashrc
```

---

## 2. Start the local model server

```bash
bash ~/claude-autonaumous/sglang/serve_sglang.sh
```

This starts the Docker container in the background. First boot takes ~6 minutes (loads 11 shards). Check readiness:

```bash
curl http://127.0.0.1:8000/health        # wait for 200 OK
bash ~/claude-autonaumous/sglang/check_server.sh
```

**To start automatically on boot:**
```bash
sudo cp ~/sglang/sglang.service /etc/systemd/system/sglang.service
sudo systemctl daemon-reload
sudo systemctl enable --now sglang
```

**Key flags used in the container** (already in `serve_sglang.sh`):

| Flag | Why |
|------|-----|
| `--security-opt seccomp=unconfined` | Triton kernel loading requires unrestricted syscalls |
| `--enforce-eager` | Skips torch.compile (saves 20+ min on first boot) |
| `--enable-auto-tool-choice --tool-call-parser qwen3_xml` | Native tool calling |
| nvfp4.py patch mounted as volume | Bypasses FlashInfer JIT on SM12.1 |

---

## 3. Using the hybrid pipeline

### Mode A — Hybrid (Claude plans, Qwen executes)

Run from inside your project directory:

```bash
cd ~/my-project
python3 ~/claude-autonaumous/main.py "Add a /health endpoint to the Flask API that returns uptime and version"
```

Or pass no argument for interactive mode:

```bash
cd ~/my-project
python3 ~/claude-autonaumous/main.py
# Enter your goal: ...
```

What happens:
1. Claude Code CLI generates a structured JSON plan (steps + constraints)
2. Each step is sent to Qwen with tool access
3. Qwen reads existing files, writes changes, runs tests, fixes failures
4. Results are printed step by step

**Environment variables** (all optional):

```bash
export WORKSPACE_DIR=/path/to/project   # default: cwd
export CLAUDE_MODEL=claude-sonnet-4-6   # default
export LOCAL_MODEL_NAME=qwen3-next-80b  # default
export LOCAL_MODEL_URL=http://127.0.0.1:8000/v1/chat/completions
export ENABLE_REVIEWER=true             # Claude reviews each step after execution
export MAX_RETRIES=3
```

### Mode B — Qwen standalone (no Claude tokens needed)

Interactive REPL, same tool access, persistent conversation context:

```bash
cd ~/my-project && qwen
```

```
You: read the codebase and explain what it does
You: add input validation to the POST /users endpoint
You: write tests for it and make sure they pass
You: /reset       ← start fresh context
You: /exit
```

Single task mode:

```bash
qwen "refactor db.py to use connection pooling"
qwen -w ~/other-project "add a Dockerfile"
```

### Mode C — Inside Claude Code (MCP tool)

When you're in a Claude Code session, I have access to two extra tools:

- **`qwen_execute(task, workspace)`** — full agentic loop (reads, writes, runs, verifies)
- **`qwen_chat(message)`** — plain chat, no file access

Example prompts to me (Claude):
- *"Use qwen to implement the auth middleware"*
- *"Delegate the test writing to the local model"*
- *"Ask qwen to refactor utils.py for readability"*

MCP is registered globally in `~/.claude/settings.json` and activates in every Claude Code session automatically.

---

## 4. Using on a different project

The model server is project-agnostic. For any new project:

```bash
# Option 1 — cd into the project
cd ~/new-project
qwen                                         # standalone Qwen
python3 ~/claude-autonaumous/main.py "..."   # hybrid pipeline

# Option 2 — workspace flag
qwen -w ~/new-project "implement feature X"

# Option 3 — env var
WORKSPACE_DIR=~/new-project python3 ~/claude-autonaumous/main.py "..."
```

---

## 5. Example project — fully automatic

A complete working example you can run right now to see the pipeline end to end.

**What it builds:** A CLI task manager — `todo.py` with add/list/complete/delete commands, persistent JSON storage, and a full test suite.

```bash
mkdir ~/todo-demo && cd ~/todo-demo

python3 ~/claude-autonaumous/main.py \
  "Build a CLI todo app in a single file todo.py. \
Commands: add <title>, list, complete <id>, delete <id>. \
Store tasks in tasks.json (create if missing). \
Each task has: id (int, auto-increment), title (str), done (bool), created_at (ISO timestamp). \
Then write tests/test_todo.py using unittest that tests all four commands including edge cases. \
Run the tests and make sure they all pass."
```

Expected output:
- `todo.py` — ~120 lines, argparse-based CLI
- `tests/test_todo.py` — full unittest suite
- All tests green, verified by Qwen

Try it manually after:
```bash
python3 todo.py add "Buy groceries"
python3 todo.py add "Write docs"
python3 todo.py list
python3 todo.py complete 1
python3 todo.py list
python3 todo.py delete 2
```

---

## 6. Token usage tracking

Every run prints a usage summary at the end showing how many tokens each model consumed:

```
[tokens] ── Usage Summary ──────────────────────────
[tokens] Claude (cloud):      3 in /   540 out  |  10,666 cache-read / 0 cache-write  |  $0.0113
[tokens] Qwen  (local):   9,923 in /   448 out  |  10,371 total
[tokens] ────────────────────────────────────────────
```

**Claude** reports real token counts from the CLI JSON output (`--output-format json`), including prompt cache hits/writes and the actual USD cost charged to your subscription.

**Qwen** reports `prompt_tokens` and `completion_tokens` from the vLLM API response. These are local compute only — no cost beyond electricity.

The tracker accumulates across all steps in a run (implemented in `utils/token_tracker.py`).

---

## Architecture reference

```
claude-autonaumous/
├── main.py                  entry point — hybrid pipeline
├── qwen_cli.py              standalone Qwen REPL / CLI
├── mcp_server.py            MCP server for Claude Code integration
│
├── core/
│   ├── orchestrator.py      main loop: plan → validate → execute → review
│   ├── planner.py           wraps ClaudeClient, returns validated plan
│   ├── executor.py          drives Qwen tool-calling loop per step
│   ├── router.py            heuristic / LLM-based task router (hybrid vs qwen)
│   └── validator.py         JSON schema validation for plans and results
│
├── models/
│   ├── claude_client.py     calls `claude --print` subprocess (no API key)
│   └── local_client.py      HTTP client + tool-calling loop for Qwen
│
├── tools/
│   ├── registry.py          TOOLS list + XML tool-call parser (single source of truth)
│   ├── file_tool.py         read_file, write_file, replace_lines, search_files, glob_files, list_directory, delete_file, move_file
│   ├── bash_tool.py         run_command (shell, with timeout)
│   ├── test_tool.py         run_tests (auto-detects pytest/npm/go/cargo/make)
│   └── git_tool.py          status, commit, diff
│
├── config/
│   └── settings.py          all config via env vars
│
├── utils/
│   ├── logger.py            structured logging setup
│   └── token_tracker.py     per-run token/cost accumulator (Claude + Qwen)
│
└── sglang/
    ├── serve_sglang.sh      docker run command (start the model server)
    ├── check_server.sh      health check + test completion
    ├── sglang.service       systemd unit (auto-start on boot)
    └── patches/
        └── nvfp4.py         SM12.1 MoE backend patch
```

### Tool-calling loop (how Qwen executes a step)

```
Orchestrator sends step description
        │
        ▼
┌─────────────────────────────────┐
│  Qwen receives step + tools     │
│                                 │
│  thinks → calls tool            │◄──┐
│  tool result injected           │   │ loop until
│  thinks → calls next tool       │───┘ no more tool_calls
│  ...                            │
│  final answer (no tool_calls)   │
└─────────────────────────────────┘
        │
        ▼
Orchestrator receives: files written, commands run, summary
```

Available tools in every agent call (13 total):

| Tool | Description |
|---|---|
| `read_file(path, start_line?, end_line?)` | Line-numbered file contents; range params avoid reading large files in full |
| `write_file(path, content)` | Full file overwrite, creates parent dirs |
| `replace_lines(path, start_line, end_line, new_content)` | Surgical line-range edit — prefer over write_file for targeted changes |
| `search_files(pattern, path?, glob?)` | Regex grep with file + line results |
| `glob_files(pattern, path?)` | Find files by pattern e.g. `**/*.py` |
| `list_directory(path, depth?)` | ASCII tree view, default depth 2 |
| `delete_file(path)` | Remove file or directory tree |
| `move_file(src, dst)` | Move or rename |
| `run_command(cmd, cwd?)` | Shell command with timeout |
| `run_tests(cmd?, timeout?)` | Auto-detect and run test suite (pytest / npm / go / cargo / make) |
| `git_status` | Working tree status |
| `git_commit(message)` | Stage all + commit |
| `git_diff` | Show unstaged/staged changes |

---

## Troubleshooting

**Model server won't start / exits immediately**
```bash
docker logs vllm-server 2>&1 | tail -30
```
Common causes: ComfyUI or another process using GPU memory — check with `free -h`.

**`Triton Error [CUDA]: operation not permitted`**
The container needs `--security-opt seccomp=unconfined` (already in `serve_sglang.sh`).

**`400 Bad Request` on tool calls**
Ensure `--enable-auto-tool-choice --tool-call-parser qwen3_xml` is in `VLLM_EXTRA_ARGS` in `serve_sglang.sh`.

**FlashInfer JIT failure (`ninja exit code 255`)**
The nvfp4.py patch is not mounted or not applied correctly. Check:
```bash
docker exec vllm-server cat /app/vllm/vllm/model_executor/layers/fused_moe/oracle/nvfp4.py | grep VLLM_CUTLASS
```

**Claude planner returns non-JSON**
Claude Code CLI occasionally wraps output in markdown. The `_strip_json_fences` helper handles this, but if planning fails try:
```bash
claude --print --model claude-sonnet-4-6 "test" 
```
to verify the CLI works.

**Streaming causes JSON parse failures on tool calls**
A known issue where SSE streaming occasionally produces empty tool-call deltas that fail JSON parsing. Disable streaming as a workaround:
```bash
STREAM_OUTPUT=false python3 ~/claude-autonaumous/main.py "your goal"
```

**Out of Claude tokens — switch to standalone Qwen**
```bash
qwen   # identical tool access, persistent context, no cloud calls
```
