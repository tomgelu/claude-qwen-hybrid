import os
import subprocess

# Commands RTK can compress. When USE_RTK=true, these are prefixed with "rtk ".
_RTK_PREFIXES = ("git ", "docker ", "ls ", "ls\n", "find ", "grep ", "curl ", "gh ",
                 "pip ", "pip3 ", "du ", "ps ", "df ", "wc ")


def _maybe_rtk(cmd: str) -> str:
    """Wrap cmd with rtk if USE_RTK env var is set and cmd is handled by rtk."""
    if os.environ.get("USE_RTK", "").lower() not in ("1", "true", "yes"):
        return cmd
    stripped = cmd.lstrip()
    if any(stripped.startswith(p) for p in _RTK_PREFIXES) or stripped in ("ls", "git", "ps", "df"):
        return "rtk " + stripped
    return cmd


def run_command(cmd: str, cwd: str = None, timeout: int = 60) -> dict:
    if cwd is None:
        from config.settings import get_workspace
        cwd = get_workspace()
    cmd = _maybe_rtk(cmd)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "Command timed out", "success": False}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e), "success": False}
