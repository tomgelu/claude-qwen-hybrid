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
            "description": (
                "Read a file with line numbers. "
                "Use start_line/end_line to read only a specific range — "
                "prefer this for large files when you know roughly where to look."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "description": "First line to read (1-indexed, inclusive)"},
                    "end_line": {"type": "integer", "description": "Last line to read (1-indexed, inclusive)"},
                },
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
            "description": (
                "List files and directories as a tree. Use depth=1 for a flat listing, "
                "depth=2 (default) for a two-level view, depth=3+ for deeper exploration. "
                "Hidden files are excluded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "depth": {"type": "integer", "description": "How many levels deep to recurse (default 2)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run the project's test suite. Auto-detects the test command from project files "
                "(pytest, npm test, go test, cargo test, make test). "
                "Pass cmd to override. Returns pass/fail, output, and a one-line summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Override test command (optional)"},
                    "timeout": {"type": "integer", "description": "Seconds before giving up (default 120)"},
                },
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
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show unstaged and staged changes in the workspace (git diff)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": (
                "Replace a range of lines in a file with new content. "
                "Use after read_file to get exact line numbers. "
                "Prefer this over write_file for targeted edits to large files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "description": "First line to replace (1-indexed, inclusive)"},
                    "end_line": {"type": "integer", "description": "Last line to replace (1-indexed, inclusive)"},
                    "new_content": {"type": "string", "description": "Replacement text for the line range"},
                },
                "required": ["path", "start_line", "end_line", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). Returns matching paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'"},
                    "path": {"type": "string", "description": "Root directory to search from (default: workspace)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file or directory (recursive for directories). Use with caution.",
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
            "name": "move_file",
            "description": "Move or rename a file or directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                },
                "required": ["src", "dst"],
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
