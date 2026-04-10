# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A hybrid agentic coding system where **Claude Code acts as the Planner** (generates a structured JSON plan) and a **local Qwen model acts as the Executor** (runs tools autonomously to implement each step). The local model runs via SGLang/vLLM on a DGX Spark (GB10, SM12.1) at `http://127.0.0.1:8000`.

## Running the system

**Start the local model server (required first):**
```bash
bash ~/claude-autonaumous/sglang/serve_sglang.sh
curl http://127.0.0.1:8000/health   # wait for 200 OK
```

**Hybrid pipeline (Claude plans, Qwen executes):**
```bash
cd ~/my-project
python3 ~/claude-autonaumous/main.py "your goal here"
python3 ~/claude-autonaumous/main.py   # interactive mode
```

**Qwen standalone REPL (no Claude tokens):**
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
| `LOCAL_MODEL_NAME` | `qwen3-next-80b` | Model name sent to vLLM |
| `LOCAL_MODEL_URL` | `http://127.0.0.1:8000/v1/chat/completions` | Local model endpoint |
| `LOCAL_MODEL_TIMEOUT` | `120` | Seconds per request |
| `STREAM_OUTPUT` | `true` | Stream tokens from local model as they arrive (set false to disable) |
| `ENABLE_REVIEWER` | `false` | Claude reviews each step; retries on "fail" verdict |
| `MAX_RETRIES` | `3` | Retries per failed step (includes max_turns retries and review failures) |

## Architecture

```
main.py → Orchestrator → Planner (ClaudeClient via `claude --print` subprocess)
                       → Executor (LocalClient → streaming tool-calling loop → dispatch)
                             tools: read_file · write_file · search_files · run_command
                                    list_directory · git_status · git_commit
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
- `tools/file_tool.py` — `read_file`, `write_file`, `diff_file`, `search_files` (regex grep across files)
- `tools/bash_tool.py` — `run_command` (subprocess with timeout, workspace resolved at call time)
- `tools/git_tool.py` — `git_status`, `git_commit`

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
