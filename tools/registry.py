"""
Shared tool definitions and XML parsing utilities for the local model agent.
Imported by models/local_client.py and qwen_cli.py to avoid duplication.
"""
import json
import re

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file with the given content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string", "description": "Full file content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for a regex pattern across files. Returns matching lines with file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "Directory or file to search (default: workspace root)"},
                    "glob": {"type": "string", "description": "File glob filter e.g. '*.py' (optional)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command, returns stdout/stderr/returncode",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                    "cwd": {"type": "string", "description": "Working directory (optional)"},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at a path",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get current git status",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Stage all changes and create a git commit",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
    },
]


def parse_xml_tool_calls(content: str) -> list[dict] | None:
    """
    Parse Qwen3-style XML tool calls from content when vLLM doesn't convert them.
    Handles: <tool_call>{"name":..., "arguments":...}</tool_call>
    Returns list of fake tool_call dicts matching OpenAI format, or None if none found.
    """
    matches = re.findall(r"<tool_call>\s*([\s\S]*?)\s*</tool_call>", content)
    if not matches:
        return None
    result = []
    for i, raw in enumerate(matches):
        try:
            parsed = json.loads(raw)
            result.append({
                "id": f"xml_{i}",
                "type": "function",
                "function": {
                    "name": parsed["name"],
                    "arguments": json.dumps(parsed.get("arguments", parsed.get("parameters", {}))),
                },
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return result if result else None


def strip_xml_tool_calls(content: str) -> str:
    """Remove XML tool call blocks from content."""
    return re.sub(r"<tool_call>[\s\S]*?</tool_call>", "", content).strip()
