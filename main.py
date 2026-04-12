#!/usr/bin/env python3
"""
Hybrid Agentic Coding System
Claude Code (Planner) + Local Model (Executor)

Routing:
  auto (default) — router picks hybrid or qwen per task
  hybrid         — always Claude plans + Qwen executes
  qwen           — always Qwen standalone

Flags:
  -w / --workspace <path>  project directory (defaults to cwd)
  --dry-run                print the plan without executing
  --resume                 resume from last saved plan in the workspace
  --hybrid / --qwen / --auto  force routing mode

Set ROUTER_MODE=llm to use Qwen for routing decisions instead of heuristics.
"""
import argparse
import os
import sys
from utils.logger import setup_logging

CYAN  = "\033[96m"
DIM   = "\033[2m"
RESET = "\033[0m"


def parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("goal", nargs="*")
    parser.add_argument("-w", "--workspace", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--hybrid", action="store_const", dest="mode", const="hybrid")
    parser.add_argument("--qwen",   action="store_const", dest="mode", const="qwen")
    parser.add_argument("--auto",   action="store_const", dest="mode", const="auto")
    parser.add_argument("-h", "--help", action="store_true")
    return parser.parse_args()


def run_hybrid(user_input: str, dry_run: bool = False, resume: bool = False) -> bool:
    from core.orchestrator import Orchestrator
    orchestrator = Orchestrator()
    state = orchestrator.run(user_input, dry_run=dry_run, resume=resume)
    if dry_run:
        return True
    return len(state["failed_steps"]) == 0


def run_qwen(user_input: str) -> bool:
    from core.executor import Executor
    executor = Executor()
    step = {
        "id": 1,
        "description": user_input,
        "files": [],
        "actions": ["implement"],
        "expected_output": "Task completed successfully",
        "depends_on": [],
    }
    result = executor.run(step, context=None)
    return result["status"] == "success"


def main():
    setup_logging()
    args = parse_args()

    if args.help:
        print(__doc__)
        sys.exit(0)

    # Apply workspace
    if args.workspace:
        ws = os.path.abspath(args.workspace)
        if not os.path.isdir(ws):
            print(f"Error: workspace not found: {ws}")
            sys.exit(1)
        os.environ["WORKSPACE_DIR"] = ws

    # Get goal
    if args.goal:
        user_input = " ".join(args.goal)
    else:
        print("Hybrid Agentic Coding System")
        print("=" * 40)
        user_input = input("Enter your goal: ").strip()
        if not user_input:
            print("No input provided.")
            sys.exit(1)

    # Routing
    mode = args.mode or "auto"
    if mode == "auto":
        from core.router import route
        backend = route(user_input)
    elif mode == "hybrid":
        backend = "hybrid"
    else:
        backend = "qwen"

    print(f"{DIM}[router] → {backend}{RESET}")
    if args.dry_run:
        print(f"{DIM}[dry-run] plan only — no execution{RESET}")
    if args.resume:
        print(f"{DIM}[resume] loading saved plan from workspace{RESET}")

    if backend == "hybrid":
        ok = run_hybrid(user_input, dry_run=args.dry_run, resume=args.resume)
    else:
        ok = run_qwen(user_input)

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
