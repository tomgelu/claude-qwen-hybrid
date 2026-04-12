#!/usr/bin/env python3
"""
benchmark.py — measure token usage, latency, and cost per model.

Runs a fixed prompt suite against every configured model (cloud + local),
plus a pipeline RTK comparison (full executor, bash tools, USE_RTK off vs on).
Appends results to benchmark_results.jsonl and regenerates BENCHMARK_REPORT.md.

Usage:
    python3 benchmark.py               # chat prompts + RTK pipeline
    python3 benchmark.py --local-only  # skip Claude chat prompts
    python3 benchmark.py --cloud-only  # skip local model chat prompts
    python3 benchmark.py --no-rtk      # skip pipeline RTK comparison
    python3 benchmark.py --show        # print recorded results, no new runs
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(__file__))
from config.settings import LOCAL_MODEL_URL, LOCAL_MODEL_NAME, LOCAL_MODEL_TIMEOUT, CLAUDE_MODEL

RESULTS_FILE = Path(__file__).parent / "benchmark_results.jsonl"
REPORT_FILE  = Path(__file__).parent / "BENCHMARK_REPORT.md"

# ── Prompt suite ──────────────────────────────────────────────────────────────
# Each prompt is short and reproducible.  Temperature=0 keeps output stable.

PROMPTS = [
    {
        "id": "hello",
        "description": "minimal",
        "text": "Reply with exactly: hello",
    },
    {
        "id": "palindrome",
        "description": "short code",
        "text": "Write a Python one-liner that checks if a string s is a palindrome.",
    },
    {
        "id": "explain",
        "description": "explanation",
        "text": "Explain what a context window is in one sentence.",
    },
    {
        "id": "function",
        "description": "medium code",
        "text": (
            "Write a Python function binary_search(arr, target) -> int "
            "that returns the index of target in sorted arr, or -1 if not found."
        ),
    },
    {
        "id": "refactor",
        "description": "code review",
        "text": (
            "Review this code and suggest one improvement:\n"
            "def get(d, k):\n    try:\n        return d[k]\n    except:\n        return None"
        ),
    },
]


# ── Pipeline task suite ───────────────────────────────────────────────────────
# Tasks are deliberately non-trivial so the agent must reason, read, and
# navigate the workspace rather than recall a memorized answer.

def _setup_multifile_refactor(workspace: str) -> None:
    from pathlib import Path
    ws = Path(workspace)

    (ws / "store.py").write_text(
        '# store.py — monolithic inventory manager\n'
        'import json\nimport os\nimport sys\n'
        'from dataclasses import dataclass, asdict\nfrom typing import Optional\n\n'
        '@dataclass\nclass Item:\n'
        '    id: int\n    name: str\n    quantity: int\n    price: float\n'
        '    category: Optional[str] = None\n\n'
        '@dataclass\nclass Store:\n'
        '    name: str\n    items: list\n\n'
        '    def add_item(self, item): self.items.append(item)\n\n'
        '    def remove_item(self, item_id):\n'
        '        self.items = [i for i in self.items if i.id != item_id]\n\n'
        '    def find_item(self, item_id):\n'
        '        return next((i for i in self.items if i.id == item_id), None)\n\n'
        '    def total_value(self):\n'
        '        return sum(i.quantity * i.price for i in self.items)\n\n'
        '    def items_by_category(self, category):\n'
        '        return [i for i in self.items if i.category == category]\n\n'
        'STORE_FILE = "store_data.json"\n\n'
        'def save_store(store, path=STORE_FILE):\n'
        '    data = {"name": store.name, "items": [asdict(i) for i in store.items]}\n'
        '    with open(path, "w") as f: json.dump(data, f, indent=2)\n\n'
        'def load_store(path=STORE_FILE):\n'
        '    if not os.path.exists(path): return Store(name="My Store", items=[])\n'
        '    with open(path) as f: data = json.load(f)\n'
        '    return Store(name=data["name"], items=[Item(**i) for i in data["items"]])\n\n'
        'def cmd_add(args):\n'
        '    store = load_store()\n'
        '    item = Item(id=len(store.items)+1, name=args[0], quantity=int(args[1]),\n'
        '                price=float(args[2]), category=args[3] if len(args)>3 else None)\n'
        '    store.add_item(item)\n    save_store(store)\n'
        '    print(f"Added: {item.name} x{item.quantity} @ ${item.price:.2f}")\n\n'
        'def cmd_remove(args):\n'
        '    store = load_store()\n    store.remove_item(int(args[0]))\n'
        '    save_store(store)\n    print(f"Removed item {args[0]}")\n\n'
        'def cmd_list(args):\n'
        '    store = load_store()\n'
        '    if not store.items: print("No items."); return\n'
        '    for i in store.items:\n'
        '        cat = f" [{i.category}]" if i.category else ""\n'
        '        print(f"  {i.id:3d}  {i.name:<20} x{i.quantity:4d}  ${i.price:8.2f}{cat}")\n'
        '    print(f"  Total value: ${store.total_value():.2f}")\n\n'
        'def cmd_show(args):\n'
        '    store = load_store()\n    item = store.find_item(int(args[0]))\n'
        '    if item: print(f"Item {item.id}: {item.name}, qty={item.quantity}")\n'
        '    else: print(f"Item {args[0]} not found")\n\n'
        'COMMANDS = {"add": cmd_add, "remove": cmd_remove, "list": cmd_list, "show": cmd_show}\n\n'
        'def main():\n'
        '    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:\n'
        '        print(f"Usage: python store.py <{\'|\'.join(COMMANDS)}> [args...]")\n'
        '        sys.exit(1)\n'
        '    COMMANDS[sys.argv[1]](sys.argv[2:])\n\n'
        'if __name__ == "__main__":\n    main()\n'
    )

    (ws / "test_store.py").write_text(
        'import pytest\nfrom store import Item, Store, save_store, load_store\n'
        'import os, tempfile\n\n'
        'def test_add(): s=Store("t",[]); s.add_item(Item(1,"A",1,1.0)); assert len(s.items)==1\n'
        'def test_remove(): s=Store("t",[Item(1,"A",1,1.0)]); s.remove_item(1); assert s.items==[]\n'
        'def test_total(): s=Store("t",[Item(1,"A",2,3.0),Item(2,"B",1,5.0)]); assert s.total_value()==11.0\n'
        'def test_category():\n'
        '    s=Store("t",[Item(1,"A",1,1.0,category="fruit"),Item(2,"B",1,1.0,category="veg")])\n'
        '    assert len(s.items_by_category("fruit"))==1\n'
        'def test_roundtrip():\n'
        '    with tempfile.NamedTemporaryFile(suffix=".json",delete=False) as f: path=f.name\n'
        '    try:\n'
        '        s=Store("Shop",[Item(1,"W",10,2.99)])\n'
        '        save_store(s,path); loaded=load_store(path)\n'
        '        assert loaded.name=="Shop" and loaded.items[0].name=="W"\n'
        '    finally: os.unlink(path)\n'
    )


def _setup_bug_hunt(workspace: str) -> None:
    from pathlib import Path
    ws = Path(workspace)

    (ws / "server.py").write_text(
        '# server.py — simple in-memory task API with 3 injected bugs\n'
        'import json\n\n'
        '_tasks: list[dict] = []\n_next_id = 1\n\n\n'
        'def get_tasks(page: int = 1, per_page: int = 10) -> list[dict]:\n'
        '    """Return a page of tasks (1-indexed)."""\n'
        '    start = (page - 1) * per_page\n'
        '    end = start + per_page + 1  # BUG 1: off-by-one, should be start + per_page\n'
        '    return _tasks[start:end]\n\n\n'
        'def get_task(task_id: int) -> dict | None:\n'
        '    return next((t for t in _tasks if t["id"] == task_id), None)\n\n\n'
        'def create_task(title: str, done: bool = False) -> dict:\n'
        '    global _next_id\n'
        '    # BUG 2: no input sanitization — title accepted without stripping whitespace\n'
        '    task = {"id": _next_id, "title": title, "done": done}\n'
        '    _tasks.append(task)\n    _next_id += 1\n    return task\n\n\n'
        'def update_task(task_id: int, **kwargs) -> dict | None:\n'
        '    task = get_task(task_id)\n'
        '    if task is None: return None\n'
        '    task.update(kwargs)\n    return task\n\n\n'
        'def delete_task(task_id: int) -> bool:\n'
        '    global _tasks\n    before = len(_tasks)\n'
        '    _tasks = [t for t in _tasks if t["id"] != task_id]\n'
        '    return len(_tasks) < before\n\n\n'
        'def not_found_status() -> int:\n'
        '    return 200  # BUG 3: should return 404\n'
    )


def _setup_git_audit(workspace: str) -> None:
    """Create a small git repo with 5 commits, the last introducing a broken import."""
    import subprocess
    from pathlib import Path
    ws = Path(workspace)

    def git(*args):
        subprocess.run(["git"] + list(args), cwd=workspace,
                       check=True, capture_output=True)

    git("init")
    git("config", "user.email", "bench@test.local")
    git("config", "user.name", "Bench")

    # Commit 1: initial utils
    (ws / "utils.py").write_text(
        'def format_timestamp(ts: float) -> str:\n'
        '    from datetime import datetime\n'
        '    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")\n\n'
        'def clamp(value, lo, hi):\n'
        '    return max(lo, min(hi, value))\n'
    )
    git("add", "utils.py")
    git("commit", "-m", "feat: add utils module")

    # Commit 2: add config
    (ws / "config.py").write_text(
        'MAX_RETRIES = 3\nDEFAULT_TIMEOUT = 30\nDEBUG = False\n'
    )
    git("add", "config.py")
    git("commit", "-m", "feat: add config defaults")

    # Commit 3: add app skeleton
    (ws / "app.py").write_text(
        'from utils import format_timestamp, clamp\nfrom config import MAX_RETRIES\n\n'
        'def run(value: float) -> str:\n'
        '    v = clamp(value, 0, 100)\n'
        '    return f"[{format_timestamp(0)}] processed {v}"\n'
    )
    git("add", "app.py")
    git("commit", "-m", "feat: initial app.py")

    # Commit 4: fix clamp edge case
    (ws / "utils.py").write_text(
        'def format_timestamp(ts: float) -> str:\n'
        '    from datetime import datetime\n'
        '    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")\n\n'
        'def clamp(value, lo, hi):\n'
        '    if lo > hi: raise ValueError(f"lo={lo} > hi={hi}")\n'
        '    return max(lo, min(hi, value))\n'
    )
    git("add", "utils.py")
    git("commit", "-m", "fix: clamp raises on invalid range")

    # Commit 5: refactor app — introduce broken import (format_date doesn't exist)
    (ws / "app.py").write_text(
        'from utils import format_date, clamp  # BUG: format_date should be format_timestamp\n'
        'from config import MAX_RETRIES\n\n'
        'def run(value: float) -> str:\n'
        '    v = clamp(value, 0, 100)\n'
        '    return f"[{format_date(0)}] processed {v}"\n'
    )
    git("add", "app.py")
    git("commit", "-m", "chore: rename timestamp helper (incomplete)")


PIPELINE_TASKS = [
    {
        "id": "csv_pipeline",
        "description": (
            "Build a Python CLI tool in csv_stats.py that reads a CSV file and computes "
            "per-column statistics (count, mean, median, stddev, null count), writing a "
            "Markdown summary report. Accept --input and --output flags. "
            "Add tests in test_csv_stats.py covering: normal data, empty column, "
            "all-null column, single-row CSV. Run the tests."
        ),
        "setup": None,
        "timeout": 240,
    },
    {
        "id": "multifile_refactor",
        "description": (
            "store.py is a monolithic inventory manager. Refactor it by splitting into "
            "three modules: models.py (Item and Store dataclasses), storage.py (save_store "
            "and load_store), and cli.py (cmd_* functions and main). Update all imports. "
            "All existing tests in test_store.py must still pass after the split."
        ),
        "setup": _setup_multifile_refactor,
        "timeout": 240,
    },
    {
        "id": "bug_hunt",
        "description": (
            "server.py has three bugs: an off-by-one in get_tasks() pagination, missing "
            "input sanitization in create_task() (title should be stripped), and "
            "not_found_status() returning 200 instead of 404. Find and fix all three, "
            "then add a targeted test for each fix in test_server.py. Run the tests."
        ),
        "setup": _setup_bug_hunt,
        "timeout": 240,
    },
    {
        "id": "git_audit",
        "description": (
            "This git repo has 5 commits. Examine the last 3 commits and write a "
            "CHANGELOG.md entry grouping the changes by type (feat/fix/chore). "
            "Then fix the broken import introduced in the most recent commit in app.py "
            "(it imports format_date which does not exist — check utils.py to find the "
            "correct name), and commit the fix."
        ),
        "setup": _setup_git_audit,
        "timeout": 240,
    },
]


# ── Model runners ─────────────────────────────────────────────────────────────

def run_claude(prompt: str, model: str) -> dict:
    """Call Claude via `claude --print --output-format json`. Returns stats dict."""
    start = time.perf_counter()
    try:
        result = subprocess.run(
            ["claude", "--print", "--model", model, "--output-format", "json", prompt],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120,
        )
        elapsed = time.perf_counter() - start

        if result.returncode != 0:
            return {"error": result.stderr.strip()[:200], "latency_s": elapsed}

        data = json.loads(result.stdout)
        usage = data.get("usage", {})
        return {
            "output": data.get("result", "")[:200],
            "input_tokens":  usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read":    usage.get("cache_read_input_tokens", 0),
            "cache_write":   usage.get("cache_creation_input_tokens", 0),
            "cost_usd":      data.get("total_cost_usd", 0.0),
            "latency_s":     round(elapsed, 2),
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "latency_s": 120.0}
    except Exception as e:
        return {"error": str(e), "latency_s": time.perf_counter() - start}


def run_local(prompt: str, model: str, url: str) -> dict:
    """Call local model via OpenAI-compatible chat completions. Returns stats dict."""
    start = time.perf_counter()
    try:
        resp = requests.post(
            url,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 512,
            },
            timeout=LOCAL_MODEL_TIMEOUT,
        )
        elapsed = time.perf_counter() - start
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        content = data["choices"][0]["message"].get("content", "")
        return {
            "output": content[:200],
            "input_tokens":  usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "latency_s":     round(elapsed, 2),
        }
    except requests.exceptions.ConnectionError:
        return {"error": "connection refused — is the server running?", "latency_s": 0.0}
    except requests.exceptions.Timeout:
        return {"error": "timeout", "latency_s": float(LOCAL_MODEL_TIMEOUT)}
    except Exception as e:
        return {"error": str(e), "latency_s": time.perf_counter() - start}


# ── RTK pipeline runner ───────────────────────────────────────────────────────

RTK_TASK = (
    "Create a Python CLI fibonacci tool in fib.py that accepts an integer n "
    "and prints fib(n). Add a test in test_fib.py and run it."
)


def run_rtk_pair(run_id: str, timestamp: str) -> list[dict]:
    """
    Run the full Claude→Qwen pipeline twice in isolated workspaces:
      once with USE_RTK=false, once with USE_RTK=true.
    Returns two result dicts (no-rtk, rtk) for recording.
    """
    import importlib
    import shutil
    import tempfile

    results = []
    base = tempfile.mkdtemp(prefix="bench_rtk_")

    try:
        for use_rtk in (False, True):
            ws = os.path.join(base, "rtk_on" if use_rtk else "rtk_off")
            os.makedirs(ws)

            os.environ["USE_RTK"]       = "true" if use_rtk else "false"
            os.environ["WORKSPACE_DIR"] = ws
            os.environ["STREAM_OUTPUT"] = "false"

            # Fresh tracker + module reload so token counts start at zero
            for mod in list(sys.modules.keys()):
                if mod.startswith(("core.", "models.", "tools.", "utils.", "config.")):
                    del sys.modules[mod]
            importlib.invalidate_caches()

            import utils.token_tracker as tt
            tt.tracker = tt.TokenTracker()

            from core.orchestrator import Orchestrator
            orch = Orchestrator()

            label = "rtk_on" if use_rtk else "rtk_off"
            sys.stdout.write(f"    pipeline ({label:<7}) ... ")
            sys.stdout.flush()

            start = time.perf_counter()

            exc = []
            import threading
            t = threading.Thread(target=lambda: (
                exc.append(None) or orch.run(RTK_TASK)
            ) if True else None, daemon=True)

            def _run():
                try:
                    orch.run(RTK_TASK)
                except Exception as e:
                    exc.append(e)
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=150)
            elapsed = time.perf_counter() - start

            import utils.token_tracker as tt2
            tr = tt2.tracker

            if t.is_alive():
                print(f"timeout after {int(elapsed)}s")
                results.append({
                    "run_id": run_id, "timestamp": timestamp,
                    "model_type": "pipeline", "model": LOCAL_MODEL_NAME,
                    "prompt_id": f"pipeline_{label}", "prompt_desc": "RTK pipeline",
                    "use_rtk": use_rtk, "error": f"timeout after {int(elapsed)}s",
                    "latency_s": round(elapsed, 2),
                })
                continue

            qwen_in  = tr._qwen_input
            qwen_out = tr._qwen_output
            tool_bytes = tr.tool_response_bytes
            claude_in  = tr._claude_input
            claude_out = tr._claude_output

            print(f"qwen {qwen_in:,}in / {qwen_out:,}out  tool_bytes={tool_bytes:,}  {int(elapsed)}s")

            results.append({
                "run_id": run_id, "timestamp": timestamp,
                "model_type": "pipeline", "model": LOCAL_MODEL_NAME,
                "prompt_id": f"pipeline_{label}", "prompt_desc": "RTK pipeline",
                "use_rtk": use_rtk,
                "input_tokens":  qwen_in,
                "output_tokens": qwen_out,
                "tool_bytes":    tool_bytes,
                "claude_input_tokens":  claude_in,
                "claude_output_tokens": claude_out,
                "latency_s": round(elapsed, 2),
            })

    finally:
        shutil.rmtree(base, ignore_errors=True)

    return results


# ── Recording ─────────────────────────────────────────────────────────────────

def record(entry: dict) -> None:
    with open(RESULTS_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_results() -> list[dict]:
    if not RESULTS_FILE.exists():
        return []
    results = []
    with open(RESULTS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return results


# ── Display ───────────────────────────────────────────────────────────────────

def print_run_table(entries: list[dict]) -> None:
    """Print a summary table for a single benchmark run."""
    print(f"\n{'Prompt':<14} {'Model':<28} {'In':>7} {'Out':>6} {'Cache-R':>8} {'Cost':>8} {'ms':>6}")
    print("─" * 82)
    for e in entries:
        if "error" in e:
            print(f"  {e['prompt_id']:<12} {e['model']:<28}  ERROR: {e['error']}")
            continue
        cache_r = e.get("cache_read", 0)
        cost = f"${e['cost_usd']:.4f}" if e.get("cost_usd") else "—"
        ms = int(e["latency_s"] * 1000)
        print(
            f"  {e['prompt_id']:<12} {e['model']:<28} "
            f"{e['input_tokens']:>7,} {e['output_tokens']:>6,} "
            f"{cache_r:>8,} {cost:>8} {ms:>6}"
        )


def show_history() -> None:
    results = load_results()
    if not results:
        print("No results recorded yet.")
        return

    # Group by run_id
    runs: dict[str, list[dict]] = {}
    for r in results:
        runs.setdefault(r.get("run_id", "unknown"), []).append(r)

    for run_id, entries in runs.items():
        ts = entries[0].get("timestamp", run_id)
        print(f"\n{'━'*82}")
        print(f"  Run: {run_id}   ({ts})")
        print_run_table(entries)

    # Aggregate per model across all runs
    from collections import defaultdict
    totals: dict[str, dict] = defaultdict(lambda: {
        "runs": 0, "input": 0, "output": 0, "cost": 0.0, "latency": 0.0
    })
    for r in results:
        if "error" in r:
            continue
        m = r["model"]
        totals[m]["runs"] += 1
        totals[m]["input"] += r.get("input_tokens", 0)
        totals[m]["output"] += r.get("output_tokens", 0)
        totals[m]["cost"] += r.get("cost_usd", 0.0)
        totals[m]["latency"] += r.get("latency_s", 0.0)

    print(f"\n{'━'*82}")
    print("  Totals across all runs:")
    print(f"  {'Model':<28} {'Runs':>5} {'Total In':>10} {'Total Out':>10} {'Total Cost':>11} {'Avg ms':>8}")
    print("  " + "─" * 76)
    for model, t in sorted(totals.items()):
        avg_ms = int(t["latency"] / t["runs"] * 1000) if t["runs"] else 0
        cost_str = f"${t['cost']:.4f}" if t["cost"] else "—"
        print(
            f"  {model:<28} {t['runs']:>5} "
            f"{t['input']:>10,} {t['output']:>10,} "
            f"{cost_str:>11} {avg_ms:>8}"
        )
    print()


# ── Markdown report ──────────────────────────────────────────────────────────

def write_report() -> None:
    """Regenerate BENCHMARK_REPORT.md from all recorded JSONL entries."""
    results = load_results()
    if not results:
        return

    from collections import defaultdict

    # Group by run_id preserving insertion order
    runs: dict[str, list[dict]] = {}
    for r in results:
        runs.setdefault(r.get("run_id", "unknown"), []).append(r)

    lines = [
        "# Benchmark Report",
        "",
        "Token usage and latency across models. Generated by `benchmark.py`.",
        "",
        "---",
        "",
    ]

    # ── Per-run sections (newest first) ──────────────────────────────────────
    for run_id, entries in reversed(list(runs.items())):
        ts = entries[0].get("timestamp", run_id)
        # Pretty-print ISO timestamp
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(ts).astimezone(timezone.utc)
            ts_pretty = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            ts_pretty = ts

        lines += [
            f"## {run_id}  —  {ts_pretty}",
            "",
            "| Prompt | Model | Type | In | Out | Cache-R | Cost | ms |",
            "|--------|-------|------|----|-----|---------|------|----|",
        ]

        for e in entries:
            if "error" in e:
                lines.append(
                    f"| {e.get('prompt_id','')} | {e.get('model','')} | {e.get('model_type','')} "
                    f"| — | — | — | — | ERROR: {e['error']} |"
                )
                continue
            cache_r = f"{e.get('cache_read', 0):,}" if e.get("cache_read") else "—"
            cost    = f"${e['cost_usd']:.4f}" if e.get("cost_usd") else "—"
            ms      = int(e["latency_s"] * 1000)
            lines.append(
                f"| {e['prompt_id']} | `{e['model']}` | {e['model_type']} "
                f"| {e['input_tokens']:,} | {e['output_tokens']:,} "
                f"| {cache_r} | {cost} | {ms} |"
            )

        lines += ["", ""]

    # ── Aggregate table ───────────────────────────────────────────────────────
    totals: dict[str, dict] = defaultdict(lambda: {
        "type": "", "runs": 0, "input": 0, "output": 0,
        "cost": 0.0, "latency": 0.0,
    })
    for r in results:
        if "error" in r:
            continue
        m = r["model"]
        totals[m]["type"]    = r.get("model_type", "")
        totals[m]["runs"]   += 1
        totals[m]["input"]  += r.get("input_tokens", 0)
        totals[m]["output"] += r.get("output_tokens", 0)
        totals[m]["cost"]   += r.get("cost_usd", 0.0)
        totals[m]["latency"] += r.get("latency_s", 0.0)

    lines += [
        "---",
        "",
        "## Aggregate totals",
        "",
        "| Model | Type | Prompt runs | Total in | Total out | Total cost | Avg latency |",
        "|-------|------|-------------|----------|-----------|------------|-------------|",
    ]
    for model, t in sorted(totals.items(), key=lambda x: x[1]["type"]):
        avg_ms  = int(t["latency"] / t["runs"] * 1000) if t["runs"] else 0
        cost_s  = f"${t['cost']:.4f}" if t["cost"] else "—"
        lines.append(
            f"| `{model}` | {t['type']} | {t['runs']} "
            f"| {t['input']:,} | {t['output']:,} | {cost_s} | {avg_ms} ms |"
        )

    # ── RTK pipeline section ─────────────────────────────────────────────────
    pipeline_entries = [r for r in results if r.get("model_type") == "pipeline" and "error" not in r]

    if pipeline_entries:
        lines += [
            "---",
            "",
            "## RTK pipeline comparison",
            "",
            "Full Claude→local pipeline run on the fibonacci task. "
            "RTK filters bash/tool output before it enters the model's context.",
            "",
            "| Run | Model | RTK | Qwen in | Qwen out | Tool bytes | Claude out | Time |",
            "|-----|-------|-----|---------|----------|------------|------------|------|",
        ]
        for e in pipeline_entries:
            rtk = "✓" if e.get("use_rtk") else "✗"
            lines.append(
                f"| {e['run_id']} | `{e['model']}` | {rtk} "
                f"| {e['input_tokens']:,} | {e['output_tokens']:,} "
                f"| {e.get('tool_bytes', 0):,} "
                f"| {e.get('claude_output_tokens', 0):,} "
                f"| {int(e['latency_s'])}s |"
            )

        # Pair up runs and show savings
        pairs: dict[str, dict] = {}
        for e in pipeline_entries:
            pairs.setdefault(e["run_id"], {})[e.get("use_rtk")] = e

        savings_rows = []
        for run_id, pair in pairs.items():
            if False in pair and True in pair:
                off, on = pair[False], pair[True]
                in_saved  = off["input_tokens"] - on["input_tokens"]
                in_pct    = in_saved / off["input_tokens"] * 100 if off["input_tokens"] else 0
                tb_saved  = off.get("tool_bytes", 0) - on.get("tool_bytes", 0)
                tb_pct    = tb_saved / off["tool_bytes"] * 100 if off.get("tool_bytes") else 0
                savings_rows.append(
                    f"| {run_id} | `{off['model']}` "
                    f"| {in_saved:+,} ({in_pct:+.1f}%) "
                    f"| {tb_saved:+,} ({tb_pct:+.1f}%) |"
                )

        if savings_rows:
            lines += [
                "",
                "**RTK savings (no-RTK minus RTK):**",
                "",
                "| Run | Model | Qwen input Δ | Tool bytes Δ |",
                "|-----|-------|--------------|--------------|",
                *savings_rows,
            ]

        lines += ["", ""]

    lines += ["", f"_Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_", ""]

    REPORT_FILE.write_text("\n".join(lines))
    print(f"Report written → {REPORT_FILE.name}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Token usage benchmark")
    parser.add_argument("--local-only", action="store_true", help="Skip Claude chat prompts")
    parser.add_argument("--cloud-only", action="store_true", help="Skip local model chat prompts")
    parser.add_argument("--no-rtk",     action="store_true", help="Skip pipeline RTK comparison")
    parser.add_argument("--show",       action="store_true", help="Print recorded results only")
    parser.add_argument("--model",      default=CLAUDE_MODEL,       help=f"Claude model (default: {CLAUDE_MODEL})")
    parser.add_argument("--local-model", default=LOCAL_MODEL_NAME,  help=f"Local model name (default: {LOCAL_MODEL_NAME})")
    args = parser.parse_args()

    if args.show:
        show_history()
        write_report()
        return

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    timestamp = datetime.now(timezone.utc).isoformat()
    run_entries = []

    models_to_run = []
    if not args.local_only:
        models_to_run.append(("cloud", args.model))
    if not args.cloud_only:
        models_to_run.append(("local", args.local_model))

    print(f"\nBenchmark run: {run_id}")
    print(f"Prompts: {len(PROMPTS)}   Models: {len(models_to_run)}")
    print(f"Results → {RESULTS_FILE.name}\n")

    for model_type, model_name in models_to_run:
        print(f"  [{model_type}] {model_name}")
        for prompt in PROMPTS:
            sys.stdout.write(f"    {prompt['id']:<14} ... ")
            sys.stdout.flush()

            if model_type == "cloud":
                stats = run_claude(prompt["text"], model_name)
            else:
                stats = run_local(prompt["text"], model_name, LOCAL_MODEL_URL)

            entry = {
                "run_id":      run_id,
                "timestamp":   timestamp,
                "model_type":  model_type,
                "model":       model_name,
                "prompt_id":   prompt["id"],
                "prompt_desc": prompt["description"],
                **stats,
            }
            record(entry)
            run_entries.append(entry)

            if "error" in stats:
                print(f"ERROR: {stats['error']}")
            else:
                ms = int(stats["latency_s"] * 1000)
                tok = f"{stats['input_tokens']:,}in / {stats['output_tokens']:,}out"
                cost = f"  ${stats['cost_usd']:.4f}" if stats.get("cost_usd") else ""
                print(f"{tok}  {ms}ms{cost}")

        print()

    print_run_table(run_entries)
    # ── RTK pipeline comparison ───────────────────────────────────────────────
    if not args.no_rtk:
        print("  [pipeline] RTK comparison")
        rtk_entries = run_rtk_pair(run_id, timestamp)
        for e in rtk_entries:
            record(e)
            run_entries.append(e)
        print()

    print(f"\nAppended {len(run_entries)} entries to {RESULTS_FILE.name}")
    write_report()
    print(f"View history: python3 benchmark.py --show\n")


if __name__ == "__main__":
    main()
