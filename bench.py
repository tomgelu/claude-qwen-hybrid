#!/usr/bin/env python3
"""
bench.py — compare pipeline token usage with and without RTK.

Runs the same task twice using the SAME Claude plan in identical fresh workspaces:
  - Run A: USE_RTK=false  (raw command output into Qwen context)
  - Run B: USE_RTK=true   (RTK-filtered output)

Prints a side-by-side comparison of Qwen token counts and context bloat.
With --runs N, runs N A/B pairs and reports averages.

Usage:
    python3 bench.py
    python3 bench.py "your task here"
    python3 bench.py --runs 3
    python3 bench.py "your task" --runs 5
"""

import argparse
import os
import sys
import shutil
import tempfile
import importlib
import threading

DEFAULT_TASK = (
    "Build a Python CLI tool in csv_stats.py that reads a CSV file and computes "
    "per-column statistics (count, mean, median, stddev, null count), then writes "
    "a Markdown summary to --output. Accept --input and --output flags. "
    "Add tests in test_csv_stats.py for normal data, empty column, all-null column, "
    "and single-row CSV. Run the tests."
)


def _fresh_modules():
    """Blow away all cached imports from this project so tracker resets cleanly."""
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith(("core.", "models.", "tools.", "utils.", "config.")):
            del sys.modules[mod_name]
    importlib.invalidate_caches()


def run_once(label: str, use_rtk: bool, workspace: str, plan: dict) -> dict:
    """Run the full pipeline in workspace using a pre-supplied plan. Returns token stats."""
    os.environ["USE_RTK"] = "true" if use_rtk else "false"
    os.environ["WORKSPACE_DIR"] = workspace
    os.environ["STREAM_OUTPUT"] = "false"

    _fresh_modules()

    import utils.token_tracker as tt_mod
    tt_mod.reset_tracker()

    from core.orchestrator import Orchestrator
    from utils.token_tracker import get_tracker
    orch = Orchestrator()

    print(f"\n{'='*60}")
    print(f"  RUN {label}  |  USE_RTK={use_rtk}  |  workspace={workspace}")
    print(f"{'='*60}", flush=True)

    RUN_TIMEOUT = 240
    exc_holder = []

    def _run():
        try:
            orch.run("", plan=plan)
        except Exception as e:
            exc_holder.append(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=RUN_TIMEOUT)
    if t.is_alive():
        print(f"\n  [bench] RUN {label} timed out after {RUN_TIMEOUT}s — partial results only",
              flush=True)
    if exc_holder:
        print(f"\n  [bench] RUN {label} error: {exc_holder[0]}", flush=True)

    tr = get_tracker()
    return {
        "label": label,
        "use_rtk": use_rtk,
        "qwen_in":    tr._qwen_input,
        "qwen_out":   tr._qwen_output,
        "tool_bytes": tr.tool_response_bytes,
        "claude_in":  tr._claude_input,
        "claude_out": tr._claude_output,
    }


def _average_stats(stats_list: list[dict]) -> dict:
    """Average numeric fields across multiple runs."""
    if not stats_list:
        return {}
    keys = ["qwen_in", "qwen_out", "tool_bytes", "claude_in", "claude_out"]
    avg = {**stats_list[0]}
    for key in keys:
        avg[key] = int(sum(s[key] for s in stats_list) / len(stats_list))
    return avg


def main():
    parser = argparse.ArgumentParser(description="RTK A/B token benchmark")
    parser.add_argument("task", nargs="?", default=None, help="Task description")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of A/B pairs to run and average (default: 1)")
    args = parser.parse_args()

    task = args.task or DEFAULT_TASK

    base = tempfile.mkdtemp(prefix="bench_")
    print(f"Task: {task[:80]}{'…' if len(task) > 80 else ''}", flush=True)
    print(f"Runs: {args.runs}  Workspaces: {base}/", flush=True)

    # Generate the plan ONCE before any module reloads — it's just a dict, survives reloads
    _fresh_modules()
    from core.planner import Planner
    print("Planning...", flush=True)
    shared_plan = Planner().plan(task)
    print(f"Plan: {shared_plan['goal']} ({len(shared_plan['steps'])} steps)", flush=True)

    all_a: list[dict] = []
    all_b: list[dict] = []

    try:
        for run_n in range(1, args.runs + 1):
            suffix = f"_{run_n}" if args.runs > 1 else ""
            ws_a = os.path.join(base, f"run_a{suffix}")
            ws_b = os.path.join(base, f"run_b{suffix}")
            os.makedirs(ws_a)
            os.makedirs(ws_b)

            if args.runs > 1:
                print(f"\n── Run {run_n}/{args.runs} ──", flush=True)

            stats_a = run_once(f"A{suffix} (no RTK)", use_rtk=False,
                               workspace=ws_a, plan=shared_plan)
            stats_b = run_once(f"B{suffix} (RTK)   ", use_rtk=True,
                               workspace=ws_b, plan=shared_plan)
            all_a.append(stats_a)
            all_b.append(stats_b)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    avg_a = _average_stats(all_a)
    avg_b = _average_stats(all_b)
    label_a = f"A (no RTK){f' avg×{args.runs}' if args.runs > 1 else ''}"
    label_b = f"B (RTK)   {f' avg×{args.runs}' if args.runs > 1 else ''}"

    print("\n")
    print("╔══════════════════════════════════════════════════════════╗")
    print("║              RTK BENCHMARK RESULTS                      ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Task: {task[:50]:<50} ║")
    print("╠════════════════════════╦═══════════════╦════════════════╣")
    print(f"║ Metric                 ║ {label_a:^13} ║ {label_b:^14} ║")
    print("╠════════════════════════╬═══════════════╬════════════════╣")

    def row(label, a_val, b_val):
        diff = b_val - a_val
        pct = (diff / a_val * 100) if a_val else 0
        sign = "▼" if diff < 0 else ("▲" if diff > 0 else " ")
        change = f"{sign}{abs(pct):.1f}%"
        print(f"║ {label:<22} ║ {a_val:>13,} ║ {b_val:>11,}  {change:>4} ║")

    row("Qwen input tokens",    avg_a["qwen_in"],    avg_b["qwen_in"])
    row("Qwen output tokens",   avg_a["qwen_out"],   avg_b["qwen_out"])
    row("Tool resp bytes",      avg_a["tool_bytes"], avg_b["tool_bytes"])
    row("Claude input tokens",  avg_a["claude_in"],  avg_b["claude_in"])
    row("Claude output tokens", avg_a["claude_out"], avg_b["claude_out"])

    print("╚════════════════════════╩═══════════════╩════════════════╝")

    if avg_a["qwen_in"] and avg_b["qwen_in"]:
        saved = avg_a["qwen_in"] - avg_b["qwen_in"]
        pct = saved / avg_a["qwen_in"] * 100
        print(f"\n  RTK saved {saved:,} Qwen input tokens ({pct:.1f}%)")
    if avg_a["tool_bytes"] and avg_b["tool_bytes"]:
        saved_b = avg_a["tool_bytes"] - avg_b["tool_bytes"]
        pct_b = saved_b / avg_a["tool_bytes"] * 100
        print(f"  RTK reduced context bloat by {saved_b:,} bytes ({pct_b:.1f}%)")


if __name__ == "__main__":
    main()
