import shlex
from tools.bash_tool import run_command


def status(cwd: str = None) -> str:
    result = run_command("git status", cwd=cwd)
    return result["stdout"] if result["success"] else result["stderr"]


def commit(message: str, cwd: str = None) -> dict:
    run_command("git add -A", cwd=cwd)
    return run_command(f"git commit -m {shlex.quote(message)}", cwd=cwd)


def diff(cwd: str = None) -> str:
    result = run_command("git diff", cwd=cwd)
    return result["stdout"]
