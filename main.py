#!/usr/bin/env python3
"""
Hybrid Agentic Coding System
Claude Code (Planner) + Local Model (Executor)

Routing:
  auto (default) — router picks hybrid or qwen per task
  hybrid         — always Claude plans + Qwen executes
  qwen           — always Qwen standalone

Set ROUTER_MODE=llm to use Qwen for routing decisions instead of heuristics.
"""
import sys
from utils.logger import setup_logging
from core.router import route

CYAN  = "\033[96m"
DIM   = "\033[2m"
RESET = "\033[0m"


def run_hybrid(user_input: str) -> bool:
    from core.orchestrator import Orchestrator
    orchestrator = Orchestrator()
    state = orchestrator.run(user_input)
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

    # Parse optional --mode flag
    args = sys.argv[1:]
    mode = "auto"
    if args and args[0] in ("--hybrid", "--qwen", "--auto"):
        mode = args[0].lstrip("-")
        args = args[1:]

    if args:
        user_input = " ".join(args)
    else:
        print("Hybrid Agentic Coding System")
        print("=" * 40)
        user_input = input("Enter your goal: ").strip()
        if not user_input:
            print("No input provided.")
            sys.exit(1)

    # Determine which backend to use
    if mode == "auto":
        backend = route(user_input)
    elif mode == "hybrid":
        backend = "hybrid"
    else:
        backend = "qwen"

    print(f"{DIM}[router] → {backend}{RESET}")

    if backend == "hybrid":
        ok = run_hybrid(user_input)
    else:
        ok = run_qwen(user_input)

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
