import fnmatch
import glob as _glob
import os
import re
import shutil
import difflib


def _read_raw(path: str) -> str:
    """Read file contents without any formatting (used internally)."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_file(path: str, start_line: int = None, end_line: int = None) -> str:
    """
    Read a file and return its contents with line numbers (e.g. '1\tline content').
    If start_line/end_line are given, only that range is returned (1-indexed, inclusive).
    """
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if start_line and i < start_line:
                continue
            if end_line and i > end_line:
                break
            lines.append(f"{i}\t{line}")
    return "".join(lines)


def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def diff_file(path: str, new_content: str) -> str:
    try:
        original = _read_raw(path).splitlines(keepends=True)
    except FileNotFoundError:
        original = []
    updated = new_content.splitlines(keepends=True)
    return "".join(difflib.unified_diff(original, updated, fromfile=path, tofile=path))


def replace_lines(path: str, start_line: int, end_line: int, new_content: str) -> dict:
    """
    Replace lines [start_line, end_line] (1-indexed, inclusive) with new_content.
    Returns {"success": True, "diff": ...} or {"error": ...}.
    """
    try:
        original = _read_raw(path)
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    lines = original.splitlines(keepends=True)
    total = len(lines)
    if start_line < 1 or end_line > total or start_line > end_line:
        return {"error": f"Line range {start_line}-{end_line} out of bounds (file has {total} lines)"}
    replacement = new_content if new_content.endswith("\n") else new_content + "\n"
    updated_lines = lines[:start_line - 1] + [replacement] + lines[end_line:]
    updated = "".join(updated_lines)
    diff = "".join(difflib.unified_diff(lines, updated_lines, fromfile=path, tofile=path))
    write_file(path, updated)
    return {"success": True, "diff": diff or "(no change)"}


def glob_files(pattern: str, path: str = ".") -> dict:
    """
    Find files matching a glob pattern under path.
    Pattern examples: '**/*.py', 'src/**/*.ts', '*.json'.
    Returns {"files": [...], "total": int}.
    """
    root = os.path.abspath(path)
    full_pattern = os.path.join(root, pattern)
    matches = _glob.glob(full_pattern, recursive=True)
    # Exclude hidden directories
    filtered = [
        m for m in matches
        if not any(part.startswith(".") for part in m.split(os.sep))
    ]
    filtered.sort()
    return {"files": filtered, "total": len(filtered)}


def delete_file(path: str) -> dict:
    """Delete a file or empty directory."""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
            return {"success": True, "deleted": path, "type": "directory"}
        else:
            os.remove(path)
            return {"success": True, "deleted": path, "type": "file"}
    except FileNotFoundError:
        return {"error": f"Not found: {path}"}
    except Exception as e:
        return {"error": str(e)}


def list_directory(path: str, depth: int = 2) -> dict:
    """
    List files and directories under path up to `depth` levels deep.
    Returns a tree structure: {"tree": str, "entries": [{"path", "type"}, ...]}.
    Hidden files/dirs (dotfiles) are skipped.
    """
    root = os.path.abspath(path)
    if not os.path.isdir(root):
        return {"error": f"Not a directory: {path}"}

    lines = []
    entries = []

    def _walk(current: str, prefix: str, current_depth: int):
        try:
            items = sorted(os.listdir(current))
        except PermissionError:
            return
        items = [i for i in items if not i.startswith(".")]
        for idx, name in enumerate(items):
            full = os.path.join(current, name)
            is_last = idx == len(items) - 1
            connector = "└── " if is_last else "├── "
            kind = "dir" if os.path.isdir(full) else "file"
            lines.append(f"{prefix}{connector}{name}{'/' if kind == 'dir' else ''}")
            entries.append({"path": full, "type": kind})
            if kind == "dir" and current_depth < depth:
                extension = "    " if is_last else "│   "
                _walk(full, prefix + extension, current_depth + 1)

    lines.append(f"{root}/")
    _walk(root, "", 1)
    return {"tree": "\n".join(lines), "entries": entries}


def move_file(src: str, dst: str) -> dict:
    """Move or rename a file or directory."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        shutil.move(src, dst)
        return {"success": True, "src": src, "dst": dst}
    except FileNotFoundError:
        return {"error": f"Source not found: {src}"}
    except Exception as e:
        return {"error": str(e)}


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
