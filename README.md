# claude-autonaumous

Claude Code (cloud) as **Planner** — any local GPU model as **Executor**.

Claude breaks your goal into a structured JSON plan. The local model executes each step autonomously using real tools: reading files, writing code, running commands, verifying output. No Anthropic API key needed — uses your Claude Code CLI subscription.

```
You
 └─▶ Claude Code (Planner)       — cloud, your subscription
        └─▶ JSON Plan
               └─▶ Local Model (Executor)   — your GPU, runs locally
                      └─▶ read_file · write_file · run_command · git · …
                             └─▶ Working code
```

---

## Quick start

> **Requirements:** Python 3.10+, NVIDIA GPU (8 GB+ VRAM), [Claude Code CLI](https://claude.ai/code)

### 1. Clone and install

```bash
git clone https://github.com/tomgelu/claude-qwen-hybrid ~/claude-autonaumous
cd ~/claude-autonaumous
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start a local model server

**Ollama** (easiest — any GPU 8 GB+):
```bash
# Install Ollama: https://ollama.com/download
ollama pull qwen2.5-coder:7b
```

**vLLM via Docker** (better throughput, 24 GB+ recommended):
```bash
cp .env.example .env
# Edit .env: set VLLM_MODEL, LOCAL_MODEL_NAME
# For gated models (Qwen2.5-72B+): set HUGGING_FACE_HUB_TOKEN
# Get a token at: https://huggingface.co/settings/tokens
docker compose up -d vllm
```

**DGX Spark / 80 GB+** (SGLang):
```bash
bash sglang/serve_sglang.sh
# Override model: SGLANG_MODEL=nvidia/Qwen3-Next-80B-A3B-Instruct-NVFP4 bash sglang/serve_sglang.sh
```

Verify the server is ready:
```bash
# Ollama:
curl http://127.0.0.1:11434/api/tags
# vLLM / SGLang:
curl http://127.0.0.1:8000/health
# Works for all backends:
bash server/check.sh
```

### 3. Configure

```bash
cp .env.example .env
```

At minimum set `LOCAL_MODEL_NAME` to the name your server uses — check with:
```bash
curl http://127.0.0.1:8000/v1/models        # vLLM / SGLang
ollama list                                  # Ollama
```

Or run the setup wizard which auto-detects your GPU and writes `.env` for you:
```bash
bash setup.sh
```

### 4. Add the `qwen` alias

```bash
echo "alias qwen='python3 $HOME/claude-autonaumous/qwen_cli.py'" >> ~/.bashrc
source ~/.bashrc
```

### 5. Register the MCP server (Claude Code integration)

```bash
claude mcp add qwen-hybrid -- python3 ~/claude-autonaumous/mcp_server.py
```

This makes `qwen_execute` and `qwen_chat` available as tools in every Claude Code session.

---

## Usage

### Hybrid pipeline — Claude plans, local model executes

```bash
# Run in the current directory
cd ~/my-project
python3 ~/claude-autonaumous/main.py "Add a /health endpoint to the Flask API"

# Point at a specific project
python3 ~/claude-autonaumous/main.py -w ~/my-project "Add a /health endpoint"

# Interactive mode
python3 ~/claude-autonaumous/main.py
```

### Preview the plan before running

```bash
python3 ~/claude-autonaumous/main.py --dry-run -w ~/my-project "Refactor the auth module"
# Prints the JSON plan Claude would generate — no files touched
```

### Resume a crashed or interrupted run

```bash
# If a run fails mid-way, the plan is saved to {workspace}/.autogen_plan.json
python3 ~/claude-autonaumous/main.py --resume -w ~/my-project "same goal"
# Skips already-completed steps and picks up from where it left off
```

### Force routing mode

```bash
python3 main.py --hybrid "build a REST API"   # always Claude plans + Qwen executes
python3 main.py --qwen   "fix the typo in utils.py"  # skip planning, Qwen acts directly
python3 main.py --auto   "..."                # default: router decides
```

### Standalone local model — no Claude tokens

```bash
cd ~/my-project
qwen                                          # interactive REPL
qwen "refactor db.py to use connection pooling"
qwen -w ~/other-project "add a Dockerfile"
```

REPL commands: `/reset` (clear context), `/exit`

### Inside Claude Code — MCP tools

After registering the MCP server, two tools are available in every Claude Code session:

```
Use qwen to implement the auth middleware in ~/my-project
```

- **`qwen_execute(task, workspace)`** — full agentic loop, Qwen reads/writes files and runs commands
- **`qwen_chat(message)`** — plain chat, no file access, fast

---

## How it works

### Planner (Claude)

Claude receives your goal + the workspace file listing and returns a structured JSON plan:

```json
{
  "goal": "Add a /health endpoint",
  "steps": [
    { "id": 1, "description": "Read app.py to understand structure", "depends_on": [] },
    { "id": 2, "description": "Add /health route to app.py", "depends_on": [1] },
    { "id": 3, "description": "Write test for /health", "depends_on": [1] },
    { "id": 4, "description": "Run tests and verify", "depends_on": [2, 3] }
  ]
}
```

### Executor (local model)

Each step runs an autonomous tool-calling loop. Steps with no dependency conflicts run in parallel. The model calls tools, gets results, and loops until it stops calling tools:

```
step received
    │
    ▼
model thinks → calls tool → result injected into context
    │◄──────────────────────────────────────────────────┘
    │  (repeats up to 30 turns)
    ▼
final summary (no tool call) → step complete
```

Context is automatically trimmed on long tasks — old tool responses are compressed so the model's context window stays manageable.

### Available tools (13)

| Tool | Description |
|---|---|
| `read_file(path, start_line?, end_line?)` | Line-numbered content; ranges avoid loading large files fully |
| `write_file(path, content)` | Full overwrite, creates parent dirs |
| `replace_lines(path, start, end, content)` | Surgical edit — prefer over `write_file` for small changes |
| `search_files(pattern, path?, glob?)` | Regex grep with file + line results |
| `glob_files(pattern, path?)` | Find files by glob e.g. `**/*.py` |
| `list_directory(path, depth?)` | ASCII tree view |
| `delete_file(path)` | Remove file or directory |
| `move_file(src, dst)` | Move or rename |
| `run_command(cmd, cwd?)` | Shell command with timeout |
| `run_tests(cmd?, timeout?)` | Auto-detect and run test suite (pytest / npm / go / cargo) |
| `git_status` | Working tree status |
| `git_commit(message)` | Stage all + commit |
| `git_diff` | Show staged and unstaged changes |

---

## Hardware tiers

| VRAM | Recommended model | Backend |
|------|-------------------|---------|
| 8 GB | `qwen2.5-coder:7b` | Ollama |
| 16 GB | `qwen2.5-coder:14b` | Ollama |
| 24 GB | `qwen2.5-coder:32b-instruct-q4_K_M` | Ollama |
| 48 GB | `Qwen/Qwen2.5-72B-Instruct` | vLLM |
| 80 GB+ | `Qwen/Qwen3-235B-A22B` or `nvidia/Qwen3-Next-80B` | vLLM / SGLang |

**Requires Python 3.10+** — check with `python3 --version`.

---

## Configuration

Copy `.env.example` to `.env` and adjust, or export env vars directly:

| Variable | Default | Description |
|---|---|---|
| `LOCAL_MODEL_URL` | `http://127.0.0.1:8000/v1/chat/completions` | OpenAI-compatible endpoint |
| `LOCAL_MODEL_NAME` | `qwen2.5-coder:7b` | Model name sent in API requests |
| `LOCAL_MODEL_TIMEOUT` | `120` | Seconds per request |
| `STREAM_OUTPUT` | `true` | Stream tokens as they arrive |
| `WORKSPACE_DIR` | cwd | Project directory for tool operations |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model for planning |
| `ENABLE_REVIEWER` | `false` | Claude reviews each step and retries on fail |
| `MAX_RETRIES` | `3` | Retries per failed step |
| `ROUTER_MODE` | `heuristic` | `heuristic` or `llm` (Qwen classifies task) |
| `USE_RTK` | `false` | Filter bash output with [RTK](https://github.com/tomgelu/rtk) to reduce Qwen context bloat |
| `HUGGING_FACE_HUB_TOKEN` | — | Required for gated models via vLLM/Docker |

---

## Token usage

Every run prints a usage summary:

```
[tokens] ── Usage Summary ──────────────────────────
[tokens] Claude (cloud):      3 in /   540 out  |  10,666 cache-read  |  $0.0113
[tokens] Qwen  (local):   9,923 in /   448 out  |  10,371 total
[tokens] Tool resp bytes: 18,432  (context bloat from cmd outputs)
```

Claude tokens come from the planner call only. Most hit the prompt cache. Local model tokens are free — local compute only.

To benchmark token savings from RTK output filtering:
```bash
python3 bench.py
```

To view benchmark results in a browser:
```bash
docker compose --profile bench up -d bench-viewer
# open http://localhost:8787
```

---

## Security note

The local model executes arbitrary shell commands in your workspace via `run_command`. Only point this at projects you control. Never run against production systems.

---

## Troubleshooting

**`Local model server not reachable`**
The server isn't running. For Ollama: `ollama serve`. For vLLM: `docker compose up -d vllm`. Then re-run.

**`400 Bad Request` on tool calls (vLLM)**
Add `--enable-auto-tool-choice --tool-call-parser hermes` (or `qwen3_xml` for Qwen3 models) to your vLLM args.

**Local model loops to max turns**
Usually means `WORKSPACE_DIR` is wrong. The executor resolves all file paths against it. Set it explicitly with `-w ~/your-project`.

**Claude planner times out**
Verify the CLI is healthy: `claude --print --output-format json "ping"`. Planning normally takes 5–30 s; the timeout is 120 s.

**Run crashed mid-way**
Use `--resume` — the plan and per-step status are saved to `{workspace}/.autogen_plan.json` after each step completes.

**Out of Claude tokens**
Switch to standalone mode: `qwen "..."` — identical tool access, no cloud calls, no planning overhead.

**Ollama: model name mismatch**
`LOCAL_MODEL_NAME` must exactly match what `ollama list` shows, e.g. `qwen2.5-coder:7b`.

---

## Project structure

```
claude-autonaumous/
├── main.py              entry point (-w, --dry-run, --resume, --hybrid/--qwen)
├── qwen_cli.py          standalone local model REPL / CLI
├── mcp_server.py        MCP server for Claude Code integration
├── bench.py             RTK A/B benchmark
├── bench_viewer.py      local HTTP dashboard for benchmark results
├── setup.sh             VRAM detection + .env wizard
│
├── core/
│   ├── orchestrator.py  parallel step execution, plan persistence, retry logic
│   ├── planner.py       calls Claude, returns validated JSON plan
│   ├── executor.py      drives local model tool-calling loop per step
│   ├── router.py        decides hybrid vs qwen-only per task
│   └── validator.py     JSON schema validation for plans
│
├── models/
│   ├── claude_client.py calls `claude --print` subprocess (no API key)
│   └── local_client.py  HTTP client + streaming tool-calling loop + context trimming
│
├── tools/
│   ├── registry.py      tool definitions + XML parser (single source of truth)
│   ├── file_tool.py     read/write/search/glob/list/delete/move/replace_lines
│   ├── bash_tool.py     run_command (with optional RTK filtering)
│   ├── test_tool.py     run_tests (auto-detects pytest/npm/go/cargo/make)
│   └── git_tool.py      status, commit, diff
│
├── config/
│   └── settings.py      all config via env vars + .env loader
│
├── server/
│   ├── ollama.sh        start Ollama with correct settings
│   ├── vllm.sh          start vLLM via Docker
│   └── check.sh         health check + smoke test
│
└── sglang/              DGX Spark / high-end setup (80 GB+)
    ├── serve_sglang.sh  launch vLLM container (SGLANG_MODEL env var to override)
    ├── check_server.sh  health check
    └── setup_sglang.sh  full install from scratch
```
