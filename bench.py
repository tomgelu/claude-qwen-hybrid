#!/usr/bin/env python3
"""
bench.py — compare pipeline token usage with and without RTK.

Runs the same task twice in identical fresh workspaces:
  - Run A: USE_RTK=false  (raw command output into Qwen context)
  - Run B: USE_RTK=true   (RTK-filtered output)

Prints a side-by-side comparison of Qwen token counts and context bloat.

Usage:
    python3 bench.py
    python3 bench.py "your task here"
"""

import os
import sys
import shutil
import tempfile
import importlib
import signal
import threading

TASK = sys.argv[1] if len(sys.argv) > 1 else (
    "Create a Python CLI fibonacci tool in fib.py. "
    "It should accept an integer n and print fib(n). "
    "Add a simple test in test_fib.py and run it."
)


def run_once(label: str, use_rtk: bool, workspace: str) -> dict:
    """Run the full pipeline in workspace, return token stats."""
    os.environ["USE_RTK"] = "true" if use_rtk else "false"
    os.environ["WORKSPACE_DIR"] = workspace
    os.environ["STREAM_OUTPUT"] = "false"  # cleaner bench output

    # Reload tracker fresh for each run (it's a module-level singleton)
    import utils.token_tracker as tt_mod
    tt_mod.tracker = tt_mod.TokenTracker()

    # Force re-import of modules that cache the tracker at import time
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith(("core.", "models.", "tools.", "utils.", "config.")):
            del sys.modules[mod_name]
    importlib.invalidate_caches()

    from core.orchestrator import Orchestrator
    orch = Orchestrator()

    print(f"\n{'='*60}")
    print(f"  RUN {label}  |  USE_RTK={use_rtk}  |  workspace={workspace}")
    print(f"{'='*60}", flush=True)

    # Run with a hard timeout so a stuck pipeline doesn't hang forever
    RUN_TIMEOUT = 120  # seconds
    exc_holder = []

    def _run():
        try:
            orch.run(TASK)
        except Exception as e:
            exc_holder.append(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=RUN_TIMEOUT)
    if t.is_alive():
        print(f"\n  [bench] RUN {label} timed out after {RUN_TIMEOUT}s — partial results only", flush=True)
    if exc_holder:
        print(f"\n  [bench] RUN {label} error: {exc_holder[0]}", flush=True)

    # Read tracker stats after run
    import utils.token_tracker as tt_mod2
    t = tt_mod2.tracker
    return {
        "label": label,
        "use_rtk": use_rtk,
        "qwen_in": t._qwen_input,
        "qwen_out": t._qwen_output,
        "tool_bytes": t.tool_response_bytes,
        "claude_in": t._claude_input,
        "claude_out": t._claude_output,
    }


def main():
    base = tempfile.mkdtemp(prefix="bench_")
    ws_a = os.path.join(base, "run_a")
    ws_b = os.path.join(base, "run_b")
    os.makedirs(ws_a)
    os.makedirs(ws_b)

    print(f"Task: {TASK}", flush=True)
    print(f"Workspaces: {base}/run_{{a,b}}", flush=True)

    try:
        stats_a = run_once("A (no RTK)", use_rtk=False, workspace=ws_a)
        stats_b = run_once("B (RTK)   ", use_rtk=True,  workspace=ws_b)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ── Comparison table ──────────────────────────────────────────
    print("\n")
    print("╔══════════════════════════════════════════════════════════╗")
    print("║              RTK BENCHMARK RESULTS                      ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Task: {TASK[:50]:<50} ║")
    print("╠════════════════════════╦═══════════════╦════════════════╣")
    print(f"║ Metric                 ║ {'A  (no RTK)':^13} ║ {'B  (RTK)':^14} ║")
    print("╠════════════════════════╬═══════════════╬════════════════╣")

    def row(label, a_val, b_val, fmt=",d"):
        diff = b_val - a_val
        pct = (diff / a_val * 100) if a_val else 0
        sign = "▼" if diff < 0 else ("▲" if diff > 0 else " ")
        change = f"{sign}{abs(pct):.1f}%"
        print(f"║ {label:<22} ║ {a_val:>13{fmt}} ║ {b_val:>11{fmt}}  {change:>4} ║")

    row("Qwen input tokens",    stats_a["qwen_in"],    stats_b["qwen_in"])
    row("Qwen output tokens",   stats_a["qwen_out"],   stats_b["qwen_out"])
    row("Tool resp bytes",      stats_a["tool_bytes"], stats_b["tool_bytes"])
    row("Claude input tokens",  stats_a["claude_in"],  stats_b["claude_in"])
    row("Claude output tokens", stats_a["claude_out"], stats_b["claude_out"])

    print("╚════════════════════════╩═══════════════╩════════════════╝")

    if stats_a["qwen_in"] and stats_b["qwen_in"]:
        saved = stats_a["qwen_in"] - stats_b["qwen_in"]
        pct = saved / stats_a["qwen_in"] * 100
        print(f"\n  RTK saved {saved:,} Qwen input tokens ({pct:.1f}%)")
    if stats_a["tool_bytes"] and stats_b["tool_bytes"]:
        saved_b = stats_a["tool_bytes"] - stats_b["tool_bytes"]
        pct_b = saved_b / stats_a["tool_bytes"] * 100
        print(f"  RTK reduced context bloat by {saved_b:,} bytes ({pct_b:.1f}%)")


if __name__ == "__main__":
    main()
