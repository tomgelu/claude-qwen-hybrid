"""
Auto-detect and run the project's test suite.
Supports: pytest, unittest, npm/yarn/pnpm, go test, cargo, make test.
"""
import os
import subprocess
from tools.bash_tool import _maybe_rtk


def _detect_command(workspace: str) -> str | None:
    files = set(os.listdir(workspace))

    if "Cargo.toml" in files:
        return "cargo test"
    if "go.mod" in files:
        return "go test ./..."
    if "package.json" in files:
        import json
        try:
            pkg = json.loads(open(os.path.join(workspace, "package.json")).read())
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                mgr = "yarn" if "yarn.lock" in files else "pnpm" if "pnpm-lock.yaml" in files else "npm"
                return f"{mgr} test"
        except Exception:
            pass
    if "pyproject.toml" in files or "setup.py" in files or "setup.cfg" in files:
        return "python -m pytest"
    # Fallback: any conftest.py or tests/ dir → pytest
    if "conftest.py" in files or "tests" in files or "test" in files:
        return "python -m pytest"
    if "Makefile" in files:
        result = subprocess.run(
            ["grep", "-q", "^test:", "Makefile"],
            cwd=workspace, capture_output=True
        )
        if result.returncode == 0:
            return "make test"
    return None


def run_tests(workspace: str, cmd: str | None = None, timeout: int = 120) -> dict:
    """
    Run the project's test suite. Auto-detects command if not provided.
    Returns {"success", "command", "stdout", "stderr", "returncode", "summary"}.
    """
    detected = cmd or _detect_command(workspace)
    if not detected:
        return {
            "success": False,
            "command": None,
            "error": "Could not detect a test command. Pass cmd= explicitly or add a test runner.",
        }

    detected = _maybe_rtk(detected)

    try:
        result = subprocess.run(
            detected,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "command": detected, "error": f"Timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "command": detected, "error": str(e)}

    stdout = result.stdout
    stderr = result.stderr
    passed = result.returncode == 0

    # Build a short summary line from the output (last non-empty line is usually the result)
    combined = (stdout + stderr).strip()
    lines = [l for l in combined.splitlines() if l.strip()]
    summary = lines[-1] if lines else ("PASSED" if passed else "FAILED")

    return {
        "success": passed,
        "command": detected,
        "returncode": result.returncode,
        "stdout": stdout[-3000:] if len(stdout) > 3000 else stdout,
        "stderr": stderr[-1000:] if len(stderr) > 1000 else stderr,
        "summary": summary,
    }
