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
import re
import subprocess
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


def capture_quality(workspace: str, state: dict) -> dict:
    """
    Extract quality metrics from a completed pipeline run.

    - Step counts come from the orchestrator state dict.
    - Test results come from running pytest in the workspace.
    """
    completed = state.get("completed_steps", [])
    failed    = state.get("failed_steps", [])
    skipped   = state.get("skipped_steps", [])

    tests_passed = 0
    tests_failed = 0

    # Run pytest in workspace if any test files exist
    test_files = [
        f for f in (os.listdir(workspace) if os.path.isdir(workspace) else [])
        if f.startswith("test_") and f.endswith(".py")
    ]
    if test_files:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--tb=no", "-q", workspace],
            capture_output=True, text=True,
        )
        output = proc.stdout + proc.stderr
        # Parse "X passed" / "X failed" from pytest summary line
        m_passed = re.search(r"(\d+) passed", output)
        m_failed = re.search(r"(\d+) failed", output)
        if m_passed:
            tests_passed = int(m_passed.group(1))
        if m_failed:
            tests_failed = int(m_failed.group(1))

    return {
        "steps_completed": len(completed),
        "steps_failed":    len(failed),
        "steps_total":     len(completed) + len(failed) + len(skipped),
        "tests_passed":    tests_passed,
        "tests_failed":    tests_failed,
    }


def _fresh_modules():
    """Blow away all cached imports from this project so tracker resets cleanly."""
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith(("core.", "models.", "tools.", "utils.", "config.")):
            del sys.modules[mod_name]
    importlib.invalidate_caches()


def _average_stats(stats_list: list[dict]) -> dict:
    """Average numeric fields across multiple runs."""
    if not stats_list:
        return {}
    keys = ["qwen_in", "qwen_out", "tool_bytes", "claude_in", "claude_out",
            "steps_completed", "steps_failed", "steps_total",
            "tests_passed", "tests_failed"]
    avg = {**stats_list[0]}
    for key in keys:
        avg[key] = int(sum(s[key] for s in stats_list) / len(stats_list))
    return avg


_METRIC_ROWS = [
    # (display label, stats key, is_separator)
    ("Qwen input tokens",    "qwen_in",          False),
    ("Qwen output tokens",   "qwen_out",         False),
    ("Tool resp bytes",      "tool_bytes",       False),
    ("Claude input tokens",  "claude_in",        False),
    ("Claude output tokens", "claude_out",       False),
    (None,                   None,               True),   # separator
    ("Steps completed",      "steps_completed",  False),
    ("Steps failed",         "steps_failed",     False),
    ("Tests passed",         "tests_passed",     False),
    ("Tests failed",         "tests_failed",     False),
]


def format_results_table(runs: list[tuple[str, dict]], task: str) -> str:
    """
    Format benchmark results for N runs (2 or 3) into a box-drawing table.

    runs: list of (label, averaged_stats) pairs — first run is the baseline
    task: task description, truncated to fit
    Returns: multi-line string (no trailing newline)
    """
    # Layout constants
    metric_w = 22
    val_w    = 13   # right-aligned number field
    chg_w    = 7    # " ▼51.3%" change indicator, padded
    col_w    = val_w + 1 + chg_w  # total per data column

    n = len(runs)
    # Total inner width: metric + borders/spaces + n data columns
    # Each col: " " + val_w + " " + chg_w + " " = col_w + 3 — but first col has no change
    # Simpler: just measure dynamically from a rendered header row

    def _cell(val: int, baseline: int) -> str:
        """Format one data cell: right-aligned value + change vs baseline."""
        num = f"{val:>{val_w},}"
        if baseline == 0 or val == baseline:
            chg = " " * chg_w
        else:
            diff = val - baseline
            pct  = diff / baseline * 100
            sign = "▼" if diff < 0 else "▲"
            chg  = f"{sign}{abs(pct):.1f}%".rjust(chg_w)
        return f"{num} {chg}"

    cell_w = val_w + 1 + chg_w  # width of one rendered cell

    # Build header cells; first column has no change indicator
    header_cells = []
    for i, (label, _) in enumerate(runs):
        lbl = label[:cell_w]
        header_cells.append(f"{lbl:^{cell_w}}")

    # Box widths
    inner_w = metric_w + 2 + (cell_w + 3) * n  # +3 for " ║ " separators
    h_sep = "═" * (metric_w + 2)
    col_seps = ("╦" + "═" * (cell_w + 2)) * n
    mid_sep  = "╬" + ("═" * (cell_w + 2) + "╬") * (n - 1) + "═" * (cell_w + 2) + "╣"
    bot_sep  = "╩" + ("═" * (cell_w + 2) + "╩") * (n - 1) + "═" * (cell_w + 2) + "╝"

    lines = []

    # Top border + title
    title = "BENCHMARK RESULTS"
    lines.append("╔" + "═" * (inner_w) + "╗")
    lines.append("║" + title.center(inner_w) + "║")
    lines.append("╠" + "═" * (inner_w) + "╣")
    lines.append("║  Task: " + task[:inner_w - 9].ljust(inner_w - 9) + "║")

    # Header row
    lines.append("╠" + h_sep + col_seps + "╗")
    hdr = " ".join(f"║ {c} " for c in header_cells)
    lines.append(f"║ {'Metric':<{metric_w}} {hdr}║")
    lines.append("╠" + h_sep + mid_sep)

    # Data rows
    baseline_stats = runs[0][1]
    for display_label, key, is_sep in _METRIC_ROWS:
        if is_sep:
            lines.append("╠" + h_sep + mid_sep)
            continue
        cells = []
        for i, (_, stats) in enumerate(runs):
            val      = stats.get(key, 0)
            baseline = baseline_stats.get(key, 0) if i > 0 else val
            cells.append(_cell(val, baseline))
        row_vals = " ".join(f"║ {c} " for c in cells)
        lines.append(f"║ {display_label:<{metric_w}} {row_vals}║")

    # Bottom border
    lines.append("╚" + h_sep.replace("═", "═") + bot_sep)

    return "\n".join(lines)


def run_once(label: str, use_rtk: bool, workspace: str, plan: dict,
             enable_phases: bool = False) -> dict:
    """Run the full pipeline in workspace using a pre-supplied plan. Returns token + quality stats."""
    os.environ["USE_RTK"]        = "true" if use_rtk else "false"
    os.environ["ENABLE_PHASES"]  = "true" if enable_phases else "false"
    os.environ["WORKSPACE_DIR"]  = workspace
    os.environ["STREAM_OUTPUT"]  = "false"

    _fresh_modules()

    import utils.token_tracker as tt_mod
    tt_mod.reset_tracker()

    from core.orchestrator import Orchestrator
    from utils.token_tracker import get_tracker
    orch = Orchestrator()

    print(f"\n{'='*60}")
    phases_tag = "  PHASES=on" if enable_phases else ""
    print(f"  RUN {label}  |  USE_RTK={use_rtk}{phases_tag}  |  workspace={workspace}")
    print(f"{'='*60}", flush=True)

    RUN_TIMEOUT = 480
    exc_holder   = []
    state_holder = []

    def _run():
        try:
            state = orch.run("", plan=plan)
            state_holder.append(state)
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

    state   = state_holder[0] if state_holder else {"completed_steps": [], "failed_steps": [], "skipped_steps": []}
    quality = capture_quality(workspace, state)

    tr = get_tracker()
    return {
        "label":     label,
        "use_rtk":   use_rtk,
        "qwen_in":   tr._qwen_input,
        "qwen_out":  tr._qwen_output,
        "tool_bytes": tr.tool_response_bytes,
        "claude_in":  tr._claude_input,
        "claude_out": tr._claude_output,
        **quality,
    }


def main():
    parser = argparse.ArgumentParser(description="RTK + phases benchmark")
    parser.add_argument("task",    nargs="?", default=None, help="Task description")
    parser.add_argument("--runs",  type=int,  default=1,
                        help="Number of A/B(/C) sets to run and average (default: 1)")
    parser.add_argument("--phases", action="store_true",
                        help="Add a third run with ENABLE_PHASES=true to compare quality impact")
    args = parser.parse_args()

    task = args.task or DEFAULT_TASK

    base = tempfile.mkdtemp(prefix="bench_")
    print(f"Task: {task[:80]}{'…' if len(task) > 80 else ''}", flush=True)
    print(f"Runs: {args.runs}  Phases: {args.phases}  Workspaces: {base}/", flush=True)

    # Generate the shared plan ONCE — survives module reloads
    _fresh_modules()
    from core.planner import Planner
    print("Planning...", flush=True)
    shared_plan = Planner().plan(task)
    print(f"Plan: {shared_plan['goal']} ({len(shared_plan['steps'])} steps)", flush=True)

    all_a: list[dict] = []
    all_b: list[dict] = []
    all_c: list[dict] = []

    try:
        for run_n in range(1, args.runs + 1):
            suffix = f"_{run_n}" if args.runs > 1 else ""
            if args.runs > 1:
                print(f"\n── Run {run_n}/{args.runs} ──", flush=True)

            ws_a = os.path.join(base, f"run_a{suffix}"); os.makedirs(ws_a)
            ws_b = os.path.join(base, f"run_b{suffix}"); os.makedirs(ws_b)

            all_a.append(run_once(f"A{suffix} (no RTK)",  use_rtk=False,
                                  workspace=ws_a, plan=shared_plan))
            all_b.append(run_once(f"B{suffix} (RTK)",     use_rtk=True,
                                  workspace=ws_b, plan=shared_plan))

            if args.phases:
                ws_c = os.path.join(base, f"run_c{suffix}"); os.makedirs(ws_c)
                all_c.append(run_once(f"C{suffix} (RTK+phases)", use_rtk=True,
                                      workspace=ws_c, plan=shared_plan,
                                      enable_phases=True))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    avg_sfx  = f" avg×{args.runs}" if args.runs > 1 else ""
    avg_a = _average_stats(all_a)
    avg_b = _average_stats(all_b)
    runs  = [(f"A (no RTK){avg_sfx}", avg_a), (f"B (RTK){avg_sfx}", avg_b)]

    if all_c:
        avg_c = _average_stats(all_c)
        runs.append((f"C (RTK+phases){avg_sfx}", avg_c))

    print("\n")
    print(format_results_table(runs, task))


if __name__ == "__main__":
    main()
