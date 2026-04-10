#!/usr/bin/env python3
"""
Qwen coding agent CLI — a Claude Code replacement powered by the local Qwen model.

Usage:
  qwen                              interactive REPL in current directory
  qwen "add auth to my Flask app"   single task, then exit
  qwen -w /path/to/project          set workspace explicitly
  qwen -w /path/to/project "task"   workspace + single task
"""
import argparse
import json
import os
import readline  # enables arrow keys / history in input()
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import LOCAL_MODEL_URL, LOCAL_MODEL_NAME, LOCAL_MODEL_TIMEOUT
from tools.registry import TOOLS, parse_xml_tool_calls, strip_xml_tool_calls
from tools.file_tool import read_file, write_file, diff_file, search_files, replace_lines, glob_files, delete_file, move_file, list_directory
from tools.bash_tool import run_command
from tools.git_tool import status as git_status, commit as git_commit, diff as git_diff
from tools.test_tool import run_tests

# ── ANSI colours ─────────────────────────────────────────────────────────────
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def _build_system_prompt(workspace: str) -> str:
    return f"""You are an autonomous coding agent running on a local machine.

You have tools to read/write files, run shell commands, and interact with git.
Working directory: {workspace}

## Starting any task
1. Check for CLAUDE.md or README first — they contain build commands, test commands, and conventions.
2. Explore the codebase (list_directory, read_file) to understand context before making changes.
3. Read every file you plan to modify. Understand the code style, existing utilities, and patterns.

## Making changes
- Complete the task fully — don't gold-plate, but don't leave it half-done.
- Prefer editing existing files over creating new ones. Never create documentation files unless asked.
- Mimic the existing code style exactly: indentation, naming, import order, comment density.
- Use existing libraries and utilities rather than reinventing them.
- Minimize comments; skip docstrings on code you didn't write. Only comment non-obvious logic.

## Verification (required after every change)
Run the relevant command (pytest, python3 script.py, linter, etc.) and check the output.
- If it fails, diagnose the error, fix it, re-run. Repeat until passing.
- Test at least one edge case or unexpected input beyond the happy path.
- Report each check: command → actual output → PASS or FAIL.

## Committing
Only commit if the user asks, or if the task explicitly calls for it. Use a clear commit message.

## Responding
Be concise. Lead with results, not reasoning. Respond conversationally between tool calls.
Do not narrate your thought process — state what you found and what you did."""


def dispatch(name: str, args: dict, workspace: str) -> str:
    try:
        if name == "read_file":
            try:
                return read_file(args["path"], start_line=args.get("start_line"), end_line=args.get("end_line"))
            except FileNotFoundError:
                return f"ERROR: file not found: {args['path']}"

        elif name == "write_file":
            path, content = args["path"], args["content"]
            diff = diff_file(path, content)
            write_file(path, content)
            print(f"\n{DIM}  ✎ {path}{RESET}")
            if diff:
                for line in diff.splitlines()[:40]:
                    if line.startswith("+"):
                        print(f"{GREEN}{line}{RESET}")
                    elif line.startswith("-"):
                        print(f"{RED}{line}{RESET}")
                    else:
                        print(f"{DIM}{line}{RESET}")
            return json.dumps({"success": True, "diff": diff or "(new file)"})

        elif name == "search_files":
            path = args.get("path", workspace)
            result = search_files(args["pattern"], path=path, glob_filter=args.get("glob", ""))
            total = result["total"]
            print(f"\n{DIM}  search '{args['pattern']}': {total} match(es){RESET}")
            return json.dumps(result)

        elif name == "run_command":
            cmd = args["cmd"]
            cwd = args.get("cwd", workspace)
            result = run_command(cmd, cwd=cwd)
            status = f"{GREEN}OK{RESET}" if result["success"] else f"{RED}FAILED{RESET}"
            print(f"\n{DIM}  $ {cmd}{RESET}  [{status}]")
            if result["stdout"].strip():
                print(f"{DIM}{result['stdout'].strip()[:500]}{RESET}")
            if result["stderr"].strip():
                print(f"{RED}{result['stderr'].strip()[:300]}{RESET}")
            return json.dumps(result)

        elif name == "list_directory":
            path = args.get("path", workspace)
            depth = args.get("depth", 2)
            result = list_directory(path, depth=depth)
            if "tree" in result:
                tree_preview = "\n".join(result["tree"].splitlines()[:20])
                print(f"\n{DIM}{tree_preview}{RESET}")
            return json.dumps(result)

        elif name == "run_tests":
            cmd = args.get("cmd")
            timeout = args.get("timeout", 120)
            result = run_tests(workspace, cmd=cmd, timeout=timeout)
            status_color = GREEN if result.get("success") else RED
            label = "PASSED" if result.get("success") else "FAILED"
            print(f"\n{DIM}  tests [{status_color}{label}{RESET}{DIM}]: {result.get('command')}{RESET}")
            if result.get("summary"):
                print(f"{DIM}  {result['summary']}{RESET}")
            return json.dumps(result)

        elif name == "git_status":
            out = git_status(cwd=workspace)
            print(f"\n{DIM}  git status: {out.strip()[:200]}{RESET}")
            return out

        elif name == "git_commit":
            result = git_commit(args["message"], cwd=workspace)
            print(f"\n{DIM}  git commit: {args['message']}{RESET}")
            return json.dumps(result)

        elif name == "git_diff":
            out = git_diff(cwd=workspace)
            print(f"\n{DIM}  git diff: {len(out.splitlines())} line(s){RESET}")
            return out

        elif name == "replace_lines":
            result = replace_lines(args["path"], args["start_line"], args["end_line"], args["new_content"])
            if result.get("success"):
                print(f"\n{DIM}  ✎ replace_lines {args['path']} [{args['start_line']}-{args['end_line']}]{RESET}")
                diff = result.get("diff", "")
                for line in diff.splitlines()[:30]:
                    if line.startswith("+"):
                        print(f"{GREEN}{line}{RESET}")
                    elif line.startswith("-"):
                        print(f"{RED}{line}{RESET}")
                    else:
                        print(f"{DIM}{line}{RESET}")
            return json.dumps(result)

        elif name == "glob_files":
            path = args.get("path", workspace)
            result = glob_files(args["pattern"], path=path)
            print(f"\n{DIM}  glob '{args['pattern']}': {result['total']} file(s){RESET}")
            return json.dumps(result)

        elif name == "delete_file":
            result = delete_file(args["path"])
            if result.get("success"):
                print(f"\n{DIM}  rm {args['path']}{RESET}")
            return json.dumps(result)

        elif name == "move_file":
            result = move_file(args["src"], args["dst"])
            if result.get("success"):
                print(f"\n{DIM}  mv {args['src']} → {args['dst']}{RESET}")
            return json.dumps(result)

        else:
            return json.dumps({"error": f"unknown tool: {name}"})

    except Exception as e:
        return json.dumps({"error": str(e)})


class QwenAgent:
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.messages = [{"role": "system", "content": _build_system_prompt(workspace)}]

    def send(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})

        for turn in range(40):
            payload = {
                "model": LOCAL_MODEL_NAME,
                "messages": self.messages,
                "tools": TOOLS,
                "tool_choice": "auto",
                "temperature": 0.1,
            }
            resp = requests.post(LOCAL_MODEL_URL, json=payload, timeout=LOCAL_MODEL_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            choice = data["choices"][0]
            msg = choice["message"]
            content = msg.get("content") or ""

            native_calls = msg.get("tool_calls")
            xml_calls = parse_xml_tool_calls(content) if not native_calls else None
            tool_calls = native_calls or xml_calls

            if not tool_calls:
                final = strip_xml_tool_calls(content)
                self.messages.append({"role": "assistant", "content": final})
                return final

            thinking = strip_xml_tool_calls(content)
            if thinking:
                print(f"\n{DIM}{thinking}{RESET}")

            self.messages.append(msg)

            if native_calls:
                tool_results = []
                for tc in tool_calls:
                    fn = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])
                    print(f"{YELLOW}  → {fn}({', '.join(f'{k}={repr(v)[:40]}' for k, v in args.items())}){RESET}")
                    result = dispatch(fn, args, self.workspace)
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })
                self.messages.extend(tool_results)
            else:
                response_parts = []
                for tc in tool_calls:
                    fn = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])
                    print(f"{YELLOW}  → {fn}({', '.join(f'{k}={repr(v)[:40]}' for k, v in args.items())}){RESET}")
                    result = dispatch(fn, args, self.workspace)
                    response_parts.append(f"<tool_response>\n{result}\n</tool_response>")
                self.messages.append({"role": "user", "content": "\n".join(response_parts)})

        return "(reached max turns)"

    def set_workspace(self, workspace: str) -> None:
        self.workspace = workspace
        self.messages[0]["content"] = _build_system_prompt(workspace)

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": _build_system_prompt(self.workspace)}]
        print(f"{DIM}  conversation reset{RESET}")


def main():
    parser = argparse.ArgumentParser(
        prog="qwen",
        description="Qwen local coding agent",
        add_help=True,
    )
    parser.add_argument(
        "-w", "--workspace",
        default=None,
        help="Project directory to work in (default: current directory)",
    )
    parser.add_argument(
        "task",
        nargs="*",
        help="Task to run (omit for interactive REPL)",
    )
    args = parser.parse_args()

    workspace = os.path.abspath(args.workspace or os.getcwd())
    os.chdir(workspace)
    os.environ["WORKSPACE_DIR"] = workspace

    print(f"{BOLD}{CYAN}Qwen Coding Agent{RESET}  {DIM}({LOCAL_MODEL_NAME}){RESET}")
    print(f"{DIM}workspace: {workspace}{RESET}")
    print(f"{DIM}commands: /reset  /workspace <path>  /exit{RESET}\n")

    agent = QwenAgent(workspace)

    if args.task:
        task = " ".join(args.task)
        print(f"{CYAN}> {task}{RESET}\n")
        reply = agent.send(task)
        print(f"\n{CYAN}Qwen:{RESET} {reply}\n")
        return

    while True:
        try:
            user = input(f"\n{BOLD}You:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not user:
            continue
        if user == "/exit":
            break
        if user == "/reset":
            agent.reset()
            continue
        if user.startswith("/workspace "):
            new_ws = os.path.abspath(user[11:].strip())
            os.chdir(new_ws)
            os.environ["WORKSPACE_DIR"] = new_ws
            agent.set_workspace(new_ws)
            print(f"{DIM}  workspace → {new_ws}{RESET}")
            continue

        print()
        reply = agent.send(user)
        print(f"\n{CYAN}Qwen:{RESET} {reply}")


if __name__ == "__main__":
    main()
