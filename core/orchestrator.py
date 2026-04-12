import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

from core.planner import Planner
from core.executor import Executor
from models.claude_client import ClaudeClient
from config.settings import ENABLE_REVIEWER, MAX_RETRIES, get_workspace
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
        self.reviewer = ClaudeClient() if ENABLE_REVIEWER else None

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
                plan = self.planner.plan(user_input)

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
