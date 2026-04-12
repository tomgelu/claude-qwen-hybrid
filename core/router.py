"""
Task router — decides whether a task should use:
  "hybrid"  → Claude plans + Qwen executes  (multi-step, architecture-level work)
  "qwen"    → Qwen standalone               (simple, single-step edits/fixes)

Routing uses a fast heuristic by default.  Set ROUTER_MODE=llm to let Qwen
itself classify the task (adds ~2-3 s but is more accurate for ambiguous prompts).
"""
import os
import re
import requests
from utils.logger import get_logger

log = get_logger(__name__)

# ── Keyword heuristics ────────────────────────────────────────────────────────

# Tasks that almost always need multi-step planning
_HYBRID_PATTERNS = re.compile(
    r"\b(build|create|implement|scaffold|design|architect|refactor|migrate|"
    r"rewrite|set up|integrate|add feature|add support|from scratch|full|"
    r"entire|whole|complete|end[- ]to[- ]end|pipeline|system|module|service|"
    r"multiple files?|several files?)\b",
    re.IGNORECASE,
)

# Tasks that are typically one-shot
_QWEN_PATTERNS = re.compile(
    r"\b(fix|patch|change|rename|delete|remove|update|tweak|adjust|move|"
    r"add (a |one |the )?(field|column|line|import|parameter|argument|test|"
    r"comment|log|print|check|validation)|bump|upgrade|format|lint|"
    r"run|execute|show|list|print|what is|explain|why)\b",
    re.IGNORECASE,
)

_LONG_TASK_THRESHOLD = 120  # chars — long prompts usually mean complex work


def _heuristic_route(task: str) -> str:
    """Fast, zero-latency routing via keyword matching."""
    if len(task) > _LONG_TASK_THRESHOLD:
        return "hybrid"
    if _HYBRID_PATTERNS.search(task):
        return "hybrid"
    if _QWEN_PATTERNS.search(task):
        return "qwen"
    # Default to hybrid when uncertain — better to over-plan than under-plan
    return "hybrid"


# ── LLM-based routing (optional) ─────────────────────────────────────────────

_ROUTER_PROMPT = """\
You are a task router.  Classify whether the following coding task requires:
  A) Simple execution — a single, focused change to one or two files, no planning needed.
  B) Complex planning — multiple steps, multiple files, or architectural decisions.

Reply with exactly one letter: A or B.

Task: {task}"""


def _llm_route(task: str) -> str:
    """Ask the local Qwen model to classify the task.  Falls back to heuristic on error."""
    from config.settings import LOCAL_MODEL_URL, LOCAL_MODEL_NAME, LOCAL_MODEL_TIMEOUT

    try:
        payload = {
            "model": LOCAL_MODEL_NAME,
            "messages": [
                {"role": "user", "content": _ROUTER_PROMPT.format(task=task)},
            ],
            "temperature": 0.0,
            "max_tokens": 4,
        }
        resp = requests.post(LOCAL_MODEL_URL, json=payload, timeout=LOCAL_MODEL_TIMEOUT)
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip().upper()
        if answer.startswith("A"):
            return "qwen"
        if answer.startswith("B"):
            return "hybrid"
    except Exception as e:
        log.warning(f"[router] LLM routing failed ({e}), falling back to heuristic")

    return _heuristic_route(task)


# ── Public API ────────────────────────────────────────────────────────────────

def route(task: str) -> str:
    """Return 'hybrid' or 'qwen' for the given task string."""
    mode = os.environ.get("ROUTER_MODE", "heuristic").lower()
    if mode == "llm":
        decision = _llm_route(task)
    else:
        decision = _heuristic_route(task)
    log.info(f"[router] '{task[:60]}{'...' if len(task) > 60 else ''}' → {decision} (mode={mode})")
    return decision

def route_phase(phase: str) -> str:
    '''Return claude or local for the given phase name.'''
    LOCAL_PHASES = {'execute'}
    model = 'local' if phase in LOCAL_PHASES else 'claude'
    log.info(f'[router] phase={phase} → {model}')
    return model