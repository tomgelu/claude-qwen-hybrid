# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A hybrid agentic coding system where **Claude Code acts as the Planner** (generates a structured JSON plan) and a **local model acts as the Executor** (runs tools autonomously to implement each step). Works with any OpenAI-compatible local model server (Ollama, vLLM, LM Studio, llama.cpp, SGLang).

## Running the system

**Start the local model server (required first):**
```bash
bash server/ollama.sh               # Ollama (easiest)
docker compose up -d                # vLLM via Docker
bash sglang/serve_sglang.sh         # SGLang on DGX Spark (80 GB+)
bash server/check.sh                # verify any backend
```

**Hybrid pipeline (Claude plans, local model executes):**
```bash
cd ~/my-project
python3 ~/claude-autonaumous/main.py "your goal here"
python3 ~/claude-autonaumous/main.py   # interactive mode
```

**Local model standalone REPL (no Claude tokens):**
```bash
qwen                              # interactive, uses cwd
qwen "implement feature X"        # single task
qwen -w ~/other-project "task"    # explicit workspace
```

**Inside Claude Code (MCP tools auto-registered):**
- `qwen_execute(task, workspace)` — full agentic loop
- `qwen_chat(message)` — plain chat, no file access

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WORKSPACE_DIR` | `cwd` | Project directory for tool operations (resolved at call time) |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude model for planning |
| `LOCAL_MODEL_NAME` | `qwen3-next-80b` | Model name sent to the server (run `curl .../v1/models` to find yours) |
| `LOCAL_MODEL_URL` | `http://127.0.0.1:8000/v1/chat/completions` | OpenAI-compatible endpoint |
| `LOCAL_MODEL_TIMEOUT` | `120` | Seconds per request |
| `STREAM_OUTPUT` | `true` | Stream tokens from local model as they arrive (set false to disable) |
| `ENABLE_REVIEWER` | `false` | Claude reviews each step; retries on "fail" verdict |
| `MAX_RETRIES` | `3` | Retries per failed step (includes max_turns retries and review failures) |

## Architecture

```
main.py → Orchestrator → Planner (ClaudeClient via `claude --print` subprocess)
                       → Executor (LocalClient → streaming tool-calling loop → dispatch)
                             tools: read_file · write_file · replace_lines · search_files
                                    glob_files · list_directory · run_command · run_tests
                                    delete_file · move_file · git_status · git_commit · git_diff
```

**Key data flow:**
1. `Planner.plan()` calls `claude --print` with user goal + workspace file listing; parses JSON plan `{goal, steps[], constraints[]}`
2. Each step includes `depends_on: number[]` — steps whose dependencies all succeeded run; steps with any failed dependency are skipped
3. `Orchestrator` iterates steps, passing prior step context to `Executor`; failed steps do not stop independent steps from running
4. `Executor.run()` calls `LocalClient.run_agent_loop()` which drives the Qwen tool-calling loop (max 30 turns, streaming)
5. On max-turns hit, retries inject context about what was already done so Qwen continues rather than restarts
6. If `ENABLE_REVIEWER=true`, Claude reviews each completed step; a "fail" verdict triggers a retry

**Tool definitions (`tools/registry.py`):**
Single source of truth for the TOOLS list and XML parsing. Imported by both `models/local_client.py` and `qwen_cli.py`.

**Tool-calling dual-format handling:**
Qwen may return tool calls as native OpenAI `tool_calls` fields OR as `<tool_call>...</tool_call>` XML in content. `parse_xml_tool_calls()` in `tools/registry.py` handles the XML fallback. Tool responses are sent back as `role: tool` (OpenAI format) or `<tool_response>` XML (fallback) accordingly.

**Streaming (`models/local_client.py`):**
`LocalClient._call_streaming()` uses `requests` SSE streaming, printing content tokens as they arrive and accumulating tool call deltas by index. Falls back to non-streaming on error.

**Workspace resolution (`config/settings.py`):**
`get_workspace()` reads `WORKSPACE_DIR` env var at call time (not import time), avoiding stale-cwd bugs when `-w` is used or workspace is switched mid-session.

**ClaudeClient (`models/claude_client.py`):**
Uses `claude --print` subprocess — no Anthropic API key needed, uses the Claude Code CLI subscription. `_strip_json_fences()` handles markdown-wrapped JSON output.

**MCP server (`mcp_server.py`):**
Registered globally in `~/.claude/settings.json`. Exposes `qwen_execute` and `qwen_chat` tools to every Claude Code session. Sets `WORKSPACE_DIR` env var rather than patching module attributes.

## Tools available to the agent

Defined in `tools/registry.py`. `Executor._dispatch()` routes calls to:
- `tools/file_tool.py` — file I/O and navigation:
  - `read_file(path, start_line?, end_line?)` — returns line-numbered content; use range params to read only the relevant section of large files
  - `write_file(path, content)` — full file overwrite, creates parent dirs
  - `replace_lines(path, start_line, end_line, new_content)` — surgical line-range replacement; prefer over write_file for targeted edits
  - `search_files(pattern, path?, glob?)` — regex grep with file/line results
  - `glob_files(pattern, path?)` — find files by glob (e.g. `**/*.py`) without reading content
  - `list_directory(path, depth?)` — ASCII tree view, default depth 2; use depth=1 for quick peek
  - `delete_file(path)` — remove file or directory tree
  - `move_file(src, dst)` — move or rename
- `tools/bash_tool.py` — `run_command(cmd, cwd?)` (subprocess with timeout, workspace resolved at call time)
- `tools/test_tool.py` — `run_tests(cmd?, timeout?)` — auto-detects test runner (pytest, npm test, go test, cargo test, make test); returns pass/fail, output, and summary line
- `tools/git_tool.py` — `git_status`, `git_commit(message)`, `git_diff`

## RTK benchmark (`bench.py`)

Measures Qwen token usage with and without [RTK](https://github.com/user/rtk) filtering on bash command output.
RTK intercepts commands like `git status`, `pytest`, etc. and strips noise before the output is fed back into Qwen's context window.

```bash
python3 bench.py                        # default fibonacci task
python3 bench.py "your custom task"     # custom task
```

**Cross-model benchmark (35B vs 80B, sequential with Docker swap):**
```bash
python3 ~/claude-autonaumous/bench_compare.py "your task"
python3 ~/claude-autonaumous/bench_compare.py "your task" --runs 3
```
Results appear in bench_viewer → "Model Comparison" section.

Runs the full Claude→Qwen pipeline twice in isolated temp workspaces (Run A: no RTK, Run B: RTK on), then prints a side-by-side token comparison.

**What the metrics mean:**
- `Qwen input tokens` — total tokens fed into Qwen across all turns; RTK reduces this by compressing tool response bytes
- `Tool resp bytes` — raw bytes of bash/tool output injected back into context; the primary lever RTK acts on
- `Claude input tokens` — only uncached tokens charged; most planning tokens hit the prompt cache (shown separately by the CLI)
- `Claude output tokens` — varies run-to-run because each run gets an independent planning call

**Observed savings (fibonacci task, ~40 turns total):** RTK saved ~6% Qwen input tokens and reduced tool context by ~5%.
Results are single-sample; run multiple times and average for reliable numbers.

**Known caveats:**
- Each run uses an independent Claude planning call, so plan structure (and thus Qwen turn count) can differ between A and B — expect some output-token noise
- `STREAM_OUTPUT` is read at `config.settings` import time; bench.py forces a full module reload (including `config.*`) to ensure the env var takes effect

## Testing

No automated test suite for this repo itself. Run the end-to-end demo to verify the pipeline:
```bash
mkdir ~/todo-demo && cd ~/todo-demo
python3 ~/claude-autonaumous/main.py "Build a CLI todo app..."
```

Check the server health:
```bash
bash ~/claude-autonaumous/sglang/check_server.sh
```

## Common issues

- **Server not starting:** `docker logs vllm-server 2>&1 | tail -30` — often GPU memory contention
- **`400 Bad Request` on tool calls:** `--enable-auto-tool-choice --tool-call-parser qwen3_xml` must be in `serve_sglang.sh`
- **FlashInfer JIT failure:** nvfp4.py patch at `sglang/patches/nvfp4.py` must be mounted in the container (SM12.1 workaround)
- **Claude planner returns non-JSON:** `_strip_json_fences` handles markdown wrapping; verify CLI with `claude --print --model claude-sonnet-4-6 "test"`
- **Streaming not working:** Set `STREAM_OUTPUT=false` to disable; check vLLM supports SSE streaming for your model
- **Executor writes files to wrong directory:** `Executor._dispatch()` resolves all relative paths against `get_workspace()`. If you add new file tools, use the `abs_path()` helper defined at the top of `_dispatch` — otherwise Qwen's relative paths land in the process cwd, commands fail, and the agent loops to max_turns
- **Claude planner subprocess hangs:** `_call_claude()` in `claude_client.py` has `timeout=120`. A planning call with the full system prompt takes 5-30s normally; if it consistently times out, check `claude --print --output-format json "ping"` to verify the CLI is healthy
