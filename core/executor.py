import json
import os
from models.local_client import LocalClient
from tools.file_tool import (
    read_file, write_file, diff_file, search_files,
    replace_lines, glob_files, delete_file, move_file, list_directory,
)
from tools.bash_tool import run_command
from tools.test_tool import run_tests
from tools.git_tool import status as git_status, commit as git_commit, diff as git_diff
from config.settings import get_workspace
from utils.logger import get_logger

log = get_logger(__name__)


class Executor:
    def __init__(self):
        self.client = LocalClient()

    def run(self, step: dict, context: list[dict] | None = None, prior_attempt: dict | None = None) -> dict:
        """Run a step via the tool-calling agent loop."""
        self._modified_files: dict[str, str] = {}
        self._commands_run: list[dict] = []

        task = f"Step {step['id']}: {step['description']}"
        if step.get("files"):
            task += f"\nFiles: {', '.join(step['files'])}"
        if step.get("expected_output"):
            task += f"\nExpected outcome: {step['expected_output']}"
        if context:
            prior = [s["step"]["description"] for s in context]
            task += f"\nAlready completed: {json.dumps(prior)}"

        if prior_attempt:
            already_modified = [f["path"] for f in prior_attempt.get("modified_files", [])]
            already_ran = prior_attempt.get("commands", [])
            task += "\n\nPrevious attempt used all turns without finishing."
            if already_modified:
                task += f"\nFiles already modified (do not redo): {', '.join(already_modified)}"
            if already_ran:
                task += f"\nCommands already run: {', '.join(already_ran[:10])}"
            task += "\nContinue from where it left off — skip already-done work."

        loop_result = self.client.run_agent_loop(task, self._dispatch)

        return {
            "status": loop_result["status"],
            "modified_files": [
                {"path": p, "content": c} for p, c in self._modified_files.items()
            ],
            "commands": [r["cmd"] for r in self._commands_run],
            "logs": loop_result.get("final_message", ""),
            "_turns": loop_result.get("turns", 0),
        }

    def _dispatch(self, name: str, args: dict):
        workspace = get_workspace()

        def abs_path(p: str) -> str:
            return p if os.path.isabs(p) else os.path.join(workspace, p)

        if name == "read_file":
            path = abs_path(args["path"])
            try:
                return {"content": read_file(path, args.get("start_line"), args.get("end_line"))}
            except FileNotFoundError:
                return {"error": f"File not found: {path}"}

        elif name == "write_file":
            path, content = abs_path(args["path"]), args["content"]
            diff = diff_file(path, content)
            write_file(path, content)
            self._modified_files[path] = content
            log.info(f"  [tool] write_file → {path}")
            if diff:
                lines = diff.splitlines()
                preview = "\n".join(lines[:30])
                if len(lines) > 30:
                    preview += f"\n... ({len(lines) - 30} more lines)"
                log.info(preview)
            return {"success": True, "diff": diff or "(new file)"}

        elif name == "search_files":
            path = args.get("path", workspace)
            result = search_files(args["pattern"], path=path, glob_filter=args.get("glob", ""))
            log.info(f"  [tool] search_files '{args['pattern']}' → {result['total']} match(es)")
            return result

        elif name == "run_command":
            cmd = args["cmd"]
            cwd = args.get("cwd", workspace)
            result = run_command(cmd, cwd=cwd)
            self._commands_run.append({"cmd": cmd, **result})
            status = "OK" if result["success"] else "FAILED"
            log.info(f"  [tool] run_command [{status}]: {cmd}")
            if result["stdout"].strip():
                log.info(f"    → {result['stdout'].strip()[:300]}")
            if result["stderr"].strip():
                log.info(f"    stderr: {result['stderr'].strip()[:200]}")
            return result

        elif name == "list_directory":
            path = abs_path(args.get("path", workspace))
            return list_directory(path, depth=int(args.get("depth", 2)))

        elif name == "run_tests":
            result = run_tests(workspace, cmd=args.get("cmd"), timeout=args.get("timeout", 120))
            status = "PASSED" if result["success"] else "FAILED"
            log.info(f"  [tool] run_tests [{status}]: {result.get('command', '?')}")
            return result

        elif name == "git_status":
            return {"output": git_status(cwd=workspace)}

        elif name == "git_commit":
            return git_commit(args["message"], cwd=workspace)

        elif name == "git_diff":
            return {"output": git_diff(cwd=workspace)}

        elif name == "replace_lines":
            path = abs_path(args["path"])
            result = replace_lines(path, int(args["start_line"]), int(args["end_line"]), args["new_content"])
            if result.get("success"):
                self._modified_files[path] = ""
                log.info(f"  [tool] replace_lines → {path} lines {args['start_line']}-{args['end_line']}")
            return result

        elif name == "glob_files":
            path = abs_path(args.get("path", workspace))
            result = glob_files(args["pattern"], path=path)
            log.info(f"  [tool] glob_files '{args['pattern']}' → {result['total']} file(s)")
            return result

        elif name == "delete_file":
            path = abs_path(args["path"])
            result = delete_file(path)
            log.info(f"  [tool] delete_file → {path}")
            return result

        elif name == "move_file":
            src = abs_path(args["src"])
            dst = abs_path(args["dst"])
            result = move_file(src, dst)
            log.info(f"  [tool] move_file {src} → {dst}")
            return result

        else:
            return {"error": f"Unknown tool: {name}"}
