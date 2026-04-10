"""
MCP server exposing the local Qwen executor to Claude Code.

Tools available inside Claude Code:
  - qwen_execute(task, workspace)  — run a full agentic coding task on Qwen
  - qwen_chat(message)             — plain chat with Qwen (no tools)
"""
import json
import sys
import os
import requests

sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP
from config.settings import LOCAL_MODEL_URL, LOCAL_MODEL_NAME, LOCAL_MODEL_TIMEOUT

mcp = FastMCP("qwen-executor")


@mcp.tool()
def qwen_execute(task: str, workspace: str = "") -> str:
    """
    Run an agentic coding task on the local Qwen model.
    Qwen will read files, write code, run commands, and verify — all autonomously.
    Returns a summary of what was done.

    Args:
        task: Natural language description of what to build or fix.
        workspace: Absolute path to the project directory (defaults to cwd).
    """
    from core.executor import Executor

    ws = os.path.abspath(workspace) if workspace else os.getcwd()
    os.environ["WORKSPACE_DIR"] = ws

    executor = Executor()
    step = {
        "id": 1,
        "description": task,
        "files": [],
        "actions": ["implement"],
        "expected_output": "Task completed successfully",
        "depends_on": [],
    }

    result = executor.run(step, context=None)

    lines = [f"Status: {result['status']}"]
    if result.get("modified_files"):
        paths = [f["path"] for f in result["modified_files"]]
        lines.append(f"Files modified: {', '.join(paths)}")
    if result.get("commands"):
        lines.append(f"Commands run: {', '.join(result['commands'])}")
    if result.get("logs"):
        lines.append(f"\nSummary:\n{result['logs']}")
    lines.append(f"\nTurns used: {result.get('_turns', '?')}")

    return "\n".join(lines)


@mcp.tool()
def qwen_chat(message: str) -> str:
    """
    Send a plain message to the local Qwen model and get a response.
    Use this for quick questions, code review, or explanations — no file access.

    Args:
        message: Your question or prompt.
    """
    payload = {
        "model": LOCAL_MODEL_NAME,
        "messages": [{"role": "user", "content": message}],
        "temperature": 0.6,
        "max_tokens": 2048,
    }
    response = requests.post(LOCAL_MODEL_URL, json=payload, timeout=LOCAL_MODEL_TIMEOUT)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


if __name__ == "__main__":
    mcp.run()
