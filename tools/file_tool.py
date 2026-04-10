import fnmatch
import os
import re
import difflib


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def diff_file(path: str, new_content: str) -> str:
    try:
        original = read_file(path).splitlines(keepends=True)
    except FileNotFoundError:
        original = []
    updated = new_content.splitlines(keepends=True)
    return "".join(difflib.unified_diff(original, updated, fromfile=path, tofile=path))


def search_files(pattern: str, path: str = ".", glob_filter: str = "") -> dict:
    """
    Search for a regex pattern across files under `path`.
    `glob_filter` optionally restricts to matching filenames (e.g. '*.py').
    Returns {"matches": [{"file": ..., "line": ..., "text": ...}, ...], "total": int}.
    """
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return {"error": f"Invalid regex: {e}"}

    matches = []
    root = os.path.abspath(path)

    if os.path.isfile(root):
        candidates = [root]
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip hidden dirs
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fname in filenames:
                if glob_filter and not fnmatch.fnmatch(fname, glob_filter):
                    continue
                candidates.append(os.path.join(dirpath, fname))

    for fpath in candidates:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    if compiled.search(line):
                        matches.append({
                            "file": fpath,
                            "line": lineno,
                            "text": line.rstrip(),
                        })
                        if len(matches) >= 200:
                            return {"matches": matches, "total": 200, "truncated": True}
        except (OSError, PermissionError):
            continue

    return {"matches": matches, "total": len(matches)}
