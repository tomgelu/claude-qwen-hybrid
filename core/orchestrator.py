import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import requests

from core.planner import Planner
from core.executor import Executor
from core.router import route_phase
from core.validator import validate_brainstorm, validate_spec
from models.claude_client import ClaudeClient, BRAINSTORM_SYSTEM_PROMPT, SPEC_SYSTEM_PROMPT
from config.settings import (
    ENABLE_REVIEWER, MAX_RETRIES, get_workspace,
    ENABLE_PHASES,
    CLAUDE_COST_BUDGET_USD, CLAUDE_TOKEN_BUDGET, CLAUDE_BUDGET_THRESHOLD,
    LOCAL_MODEL_URL, LOCAL_MODEL_NAME, LOCAL_MODEL_TIMEOUT,
)
from utils.logger import get_logger
from utils.token_tracker import get_tracker

log = get_logger(__name__)

_PLAN_FILE = ".autogen_plan.json"


def _plan_path() -> str:
    return os.path.join(get_workspace(), _PLAN_FILE)


def _save_plan(plan: dict, step_statuses: dict) -> None:
    """Persist plan + per-step status to workspace so --resume can pick up."""
    data = {"plan": plan, "step_statuses": step_statuses}
    try:
        with open(_plan_path(), "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _load_plan() -> tuple[dict, dict] | None:
    """Load a saved plan. Returns (plan, step_statuses) or None."""
    path = _plan_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data["plan"], data.get("step_statuses", {})
    except Exception:
        return None


class Orchestrator:
    def __init__(self):
        self.planner = Planner()
        self.claude_client = ClaudeClient()
        self.reviewer = self.claude_client if ENABLE_REVIEWER else None
        # Set to True once Claude hits rate limit — all subsequent phase calls use local
        self._claude_degraded = False

    # ── Budget check ──────────────────────────────────────────────────────────

    def _budget_exceeded(self) -> bool:
        """Return True if Claude spend has crossed the configured threshold."""
        tracker = get_tracker()

        # USD budget (preferred — works on API billing)
        if CLAUDE_COST_BUDGET_USD > 0:
            spent = tracker._claude_cost_usd
            limit = CLAUDE_COST_BUDGET_USD * CLAUDE_BUDGET_THRESHOLD
            if spent >= limit:
                log.warning(
                    f"[budget] ${spent:.4f} spent ≥ {CLAUDE_BUDGET_THRESHOLD*100:.0f}% of "
                    f"${CLAUDE_COST_BUDGET_USD:.2f} budget — routing to local"
                )
                return True

        # Token budget fallback (for subscription mode where cost is always 0)
        if CLAUDE_TOKEN_BUDGET > 0:
            spent = tracker._claude_input
            limit = CLAUDE_TOKEN_BUDGET * CLAUDE_BUDGET_THRESHOLD
            if spent >= limit:
                log.warning(
                    f"[budget] {spent:,} input tokens ≥ {CLAUDE_BUDGET_THRESHOLD*100:.0f}% of "
                    f"{CLAUDE_TOKEN_BUDGET:,} token budget — routing to local"
                )
                return True

        return False

    # ── Local model chat (single, no tool loop) ───────────────────────────────

    def _call_local(self, system_prompt: str, user_message: str) -> dict:
        """Call the local model for a single chat turn and return parsed JSON."""
        payload = {
            "model": LOCAL_MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.0,
        }
        resp = requests.post(LOCAL_MODEL_URL, json=payload, timeout=LOCAL_MODEL_TIMEOUT)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if present
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if match:
            content = match.group(1).strip()
        return json.loads(content)

    # ── Centralized model call with budget-aware routing ─────────────────────

    def _call_model(self, phase: str, system_prompt: str, user_message: str) -> dict:
        """
        Route a phase call to Claude or local model.

        Routing order:
          1. route_phase() gives the default model for this phase.
          2. If Claude is the default but budget is exceeded → downgrade to local.
          3. If Claude call raises a rate-limit error → degrade permanently to local.
          4. Local model is always a fallback and never budget-gated.
        """
        target = route_phase(phase)

        if target == "claude" and (self._claude_degraded or self._budget_exceeded()):
            log.info(f"[phase] {phase} → falling back to local model")
            target = "local"

        if target == "claude":
            try:
                return self.claude_client.call(system_prompt, user_message)
            except RuntimeError as e:
                if "rate" in str(e).lower() or "limit" in str(e).lower():
                    log.warning(f"[budget] Claude rate limited on phase={phase} — degrading to local for session")
                    self._claude_degraded = True
                else:
                    log.warning(f"[phase] Claude failed on phase={phase} ({e}) — falling back to local")
                return self._call_local(system_prompt, user_message)

        # target == "local"
        return self._call_local(system_prompt, user_message)

    # ── Phase: brainstorm ─────────────────────────────────────────────────────

    def _brainstorm(self, user_input: str) -> dict:
        """
        Phase 1 — clarify intent, surface approaches, flag ambiguities.
        Returns a validated BrainstormResult dict.
        """
        log.info("[phase] brainstorm ...")
        user_message = f"User goal:\n{user_input}"
        raw = self._call_model("brainstorm", BRAINSTORM_SYSTEM_PROMPT, user_message)
        result = validate_brainstorm(raw)
        log.info(f"[phase] brainstorm done — intent: {result['intent'][:80]}")
        log.info(f"[phase] brainstorm — recommended: {result['recommended_approach'][:80]}")
        return result

    # ── Phase: spec ───────────────────────────────────────────────────────────

    def _spec(self, user_input: str, brainstorm: dict | None) -> dict:
        """
        Phase 2 — convert brainstorm into structured requirements.
        Returns a validated SpecResult dict.
        """
        log.info("[phase] spec ...")
        ctx = json.dumps(brainstorm, indent=2) if brainstorm else "{}"
        user_message = (
            f"User goal:\n{user_input}\n\n"
            f"Brainstorm:\n{ctx}"
        )
        raw = self._call_model("spec", SPEC_SYSTEM_PROMPT, user_message)
        result = validate_spec(raw)
        log.info(f"[phase] spec done — {len(result['requirements'])} requirements, "
                 f"{len(result['constraints'])} constraints")
        return result

    # ── Main run ──────────────────────────────────────────────────────────────

    def run(self, user_input: str, dry_run: bool = False, resume: bool = False,
            plan: dict | None = None) -> dict:
        # ── Load or generate plan ─────────────────────────────────────────────
        if plan is not None:
            log.info(f"[orchestrator] Using pre-supplied plan: {plan['goal']}")
            step_statuses: dict[str, str] = {}
        else:
            step_statuses: dict[str, str] = {}

            if resume:
                saved = _load_plan()
                if saved:
                    plan, step_statuses = saved
                    log.info(f"[orchestrator] Resuming plan: {plan['goal']}")
                    log.info(f"[orchestrator] Already completed: {[k for k,v in step_statuses.items() if v == 'completed']}")
                else:
                    log.info("[orchestrator] No saved plan found — starting fresh")
                    resume = False

            if not resume:
                log.info(f"\n[orchestrator] Planning for: {user_input}\n")

                brainstorm_result = None
                spec_result = None

                if ENABLE_PHASES:
                    # ── Phase: brainstorm ─────────────────────────────────────
                    try:
                        brainstorm_result = self._brainstorm(user_input)
                    except Exception as e:
                        log.warning(f"[orchestrator] Brainstorm phase failed: {e} — continuing without")

                    # ── Phase: spec ───────────────────────────────────────────
                    try:
                        spec_result = self._spec(user_input, brainstorm_result)
                    except Exception as e:
                        log.warning(f"[orchestrator] Spec phase failed: {e} — continuing without")

                # ── Phase: plan ───────────────────────────────────────────────
                plan = self.planner.plan(
                    user_input,
                    brainstorm=brainstorm_result,
                    spec=spec_result,
                )

        log.info(f"[orchestrator] Goal: {plan['goal']}")
        log.info(f"[orchestrator] Steps ({len(plan['steps'])}):")
        for s in plan["steps"]:
            deps = f" (after {s['depends_on']})" if s.get("depends_on") else ""
            status = f" [{step_statuses.get(str(s['id']), 'pending')}]" if step_statuses else ""
            log.info(f"  {s['id']}.{status} {s['description']}{deps}")
        if plan.get("constraints"):
            log.info(f"[orchestrator] Constraints: {plan['constraints']}")

        # ── Dry-run: print plan and stop ──────────────────────────────────────
        if dry_run:
            print("\n" + json.dumps(plan, indent=2))
            return {"goal": plan["goal"], "completed_steps": [], "failed_steps": [],
                    "skipped_steps": [], "results": []}

        # ── Save plan before execution starts ─────────────────────────────────
        _save_plan(plan, step_statuses)

        state = {
            "goal": plan["goal"],
            "completed_steps": [],
            "failed_steps": [],
            "skipped_steps": [],
            "results": [],
        }

        # Pre-populate state with already-completed steps from a resume
        completed_ids: set[int] = set()
        failed_ids: set[int] = set()
        completed_context: list[dict] = []
        context_lock = threading.Lock()

        for step in plan["steps"]:
            sid = step["id"]
            status = step_statuses.get(str(sid))
            if status == "completed":
                completed_ids.add(sid)
                state["completed_steps"].append(sid)
                state["results"].append({"step_id": sid, "result": {"status": "completed (resumed)"}})
            elif status in ("failed", "error"):
                failed_ids.add(sid)
                state["failed_steps"].append(sid)

        # ── Parallel execution ────────────────────────────────────────────────
        pending = {
            step["id"]: step for step in plan["steps"]
            if str(step["id"]) not in step_statuses
               or step_statuses[str(step["id"])] not in ("completed",)
        }

        with ThreadPoolExecutor(max_workers=4) as pool:
            running: dict[int, object] = {}  # step_id -> Future

            while pending or running:
                # Find steps whose deps are all satisfied
                startable = []
                for sid, step in list(pending.items()):
                    deps = step.get("depends_on", [])
                    if any(d in failed_ids for d in deps):
                        # A dep failed — skip this step immediately
                        log.info(f"\n[step {sid}] SKIPPED — dependency failed: "
                                 f"{[d for d in deps if d in failed_ids]}")
                        failed_ids.add(sid)
                        state["skipped_steps"].append(sid)
                        state["results"].append({
                            "step_id": sid,
                            "result": {"status": "skipped", "reason": "dependency failed"},
                        })
                        step_statuses[str(sid)] = "skipped"
                        del pending[sid]
                    elif all(d in completed_ids for d in deps):
                        startable.append(step)

                for step in startable:
                    with context_lock:
                        ctx_snapshot = list(completed_context)
                    log.info(f"\n[step {step['id']}] Starting: {step['description']}")
                    future = pool.submit(self._run_step_with_retry, step, ctx_snapshot)
                    running[step["id"]] = future
                    del pending[step["id"]]

                if not running:
                    # Nothing running and nothing startable — we're stuck (cycle or all skipped)
                    break

                # Wait for the first step to finish
                future_to_id = {f: sid for sid, f in running.items()}
                done, _ = wait(running.values(), return_when=FIRST_COMPLETED)

                for future in done:
                    sid = future_to_id[future]
                    step = next(s for s in plan["steps"] if s["id"] == sid)
                    del running[sid]

                    result = future.result()

                    if result["status"] == "success":
                        modified = [f["path"] for f in result.get("modified_files", [])]
                        if modified:
                            log.info(f"  [files] {', '.join(modified)}")
                        log.info(f"  [agent] {result.get('_turns', '?')} turn(s)")
                        log.info(f"  [step {sid}] COMPLETED")

                        with context_lock:
                            completed_context.append({"step": step, "result": result})
                        completed_ids.add(sid)
                        state["completed_steps"].append(sid)
                        step_statuses[str(sid)] = "completed"
                    else:
                        log.info(f"  [step {sid}] FAILED: {result.get('logs', '')[:200]}")
                        failed_ids.add(sid)
                        state["failed_steps"].append(sid)
                        step_statuses[str(sid)] = "failed"

                    state["results"].append({"step_id": sid, "result": result})
                    _save_plan(plan, step_statuses)

        completed = state["completed_steps"]
        failed    = state["failed_steps"]
        skipped   = state["skipped_steps"]
        log.info(
            f"\n[orchestrator] Done. "
            f"Completed: {completed} | Failed: {failed} | Skipped: {skipped}"
        )
        if get_tracker().has_data():
            log.info("\n" + get_tracker().summary())

        # Clean up plan file on full success
        if not failed and not skipped:
            try:
                os.remove(_plan_path())
            except FileNotFoundError:
                pass

        return state

    def _run_step_with_retry(self, step: dict, context: list[dict] | None = None) -> dict:
        executor = Executor()  # fresh instance per step — safe for parallel execution
        prior_attempt = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = executor.run(step, context=context, prior_attempt=prior_attempt)

                if result["status"] == "max_turns":
                    get_tracker().retry_count += 1
                    log.warning(
                        f"  [retry {attempt}/{MAX_RETRIES}] step {step['id']} max turns"
                        + (" — retrying" if attempt < MAX_RETRIES else " — giving up")
                    )
                    prior_attempt = result
                    if attempt == MAX_RETRIES:
                        result["status"] = "error"
                    continue

                if result["status"] == "success" and self.reviewer:
                    get_tracker().reviewer_calls += 1
                    review = self.reviewer.review(result)
                    result["review"] = review
                    log.info(f"  [review] {review.get('validation', 'N/A')}: {review.get('summary', '')}")
                    if review.get("validation") == "fail" and attempt < MAX_RETRIES:
                        get_tracker().retry_count += 1
                        issues = "; ".join(review.get("issues", []))
                        log.warning(f"  [retry {attempt}/{MAX_RETRIES}] review failed: {issues}")
                        prior_attempt = result
                        continue

                return result

            except Exception as e:
                log.warning(f"  [retry {attempt}/{MAX_RETRIES}] step {step['id']} error: {e}")
                if attempt == MAX_RETRIES:
                    return {"status": "error", "modified_files": [], "commands": [], "logs": str(e)}

        return {"status": "error", "modified_files": [], "commands": [], "logs": "All retries exhausted"}
