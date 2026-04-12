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
