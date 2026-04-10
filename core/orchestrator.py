from core.planner import Planner
from core.executor import Executor
from models.claude_client import ClaudeClient
from config.settings import ENABLE_REVIEWER, MAX_RETRIES
from utils.logger import get_logger
from utils.token_tracker import tracker as _tracker

log = get_logger(__name__)


class Orchestrator:
    def __init__(self):
        self.planner = Planner()
        self.executor = Executor()
        self.reviewer = ClaudeClient() if ENABLE_REVIEWER else None

    def run(self, user_input: str) -> dict:
        log.info(f"\n[orchestrator] Planning for: {user_input}\n")

        plan = self.planner.plan(user_input)
        log.info(f"[orchestrator] Goal: {plan['goal']}")
        log.info(f"[orchestrator] Steps: {len(plan['steps'])}")
        if plan["constraints"]:
            log.info(f"[orchestrator] Constraints: {plan['constraints']}")

        state = {
            "goal": plan["goal"],
            "current_step": 0,
            "completed_steps": [],
            "failed_steps": [],
            "skipped_steps": [],
            "results": [],
        }

        completed_context: list[dict] = []
        failed_ids: set[int] = set()

        for step in plan["steps"]:
            step_id = step["id"]
            state["current_step"] = step_id

            # Skip if any dependency failed
            deps = step.get("depends_on", [])
            blocked = [d for d in deps if d in failed_ids]
            if blocked:
                log.info(f"\n[step {step_id}] SKIPPED — dependency failed: {blocked}")
                state["skipped_steps"].append(step_id)
                failed_ids.add(step_id)
                state["results"].append({
                    "step_id": step_id,
                    "result": {"status": "skipped", "reason": f"dependency failed: {blocked}"},
                })
                continue

            log.info(f"\n[step {step_id}] {step['description']}")

            result = self._run_step_with_retry(step, context=completed_context)

            if result["status"] == "success":
                modified = [f["path"] for f in result.get("modified_files", [])]
                if modified:
                    log.info(f"  [files] {', '.join(modified)}")
                log.info(f"  [agent] completed in {result.get('_turns', '?')} turn(s)")
                log.info(f"  [step {step_id}] COMPLETED")

                completed_context.append({"step": step, "result": result})
                state["completed_steps"].append(step_id)
                state["results"].append({"step_id": step_id, "result": result})
            else:
                log.info(f"  [step {step_id}] FAILED: {result.get('logs', '')}")
                failed_ids.add(step_id)
                state["failed_steps"].append(step_id)
                state["results"].append({"step_id": step_id, "result": result})
                # Continue — remaining independent steps will still run

        completed = state["completed_steps"]
        failed = state["failed_steps"]
        skipped = state["skipped_steps"]
        log.info(
            f"\n[orchestrator] Done. "
            f"Completed: {completed} | Failed: {failed} | Skipped: {skipped}"
        )
        if _tracker.has_data():
            log.info("\n" + _tracker.summary())
        return state

    def _run_step_with_retry(self, step: dict, context: list[dict] | None = None) -> dict:
        prior_attempt = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = self.executor.run(step, context=context, prior_attempt=prior_attempt)

                if result["status"] == "max_turns":
                    log.warning(
                        f"  [retry {attempt}/{MAX_RETRIES}] Max turns reached"
                        + (" — retrying with prior context" if attempt < MAX_RETRIES else " — giving up")
                    )
                    prior_attempt = result
                    if attempt == MAX_RETRIES:
                        result["status"] = "error"
                    continue

                # Run reviewer if enabled
                if result["status"] == "success" and self.reviewer:
                    review = self.reviewer.review(result)
                    result["review"] = review
                    log.info(f"  [review] {review.get('validation', 'N/A')}: {review.get('summary', '')}")
                    if review.get("validation") == "fail" and attempt < MAX_RETRIES:
                        issues = "; ".join(review.get("issues", []))
                        log.warning(f"  [retry {attempt}/{MAX_RETRIES}] Review failed: {issues}")
                        prior_attempt = result
                        continue

                return result

            except Exception as e:
                log.warning(f"  [retry {attempt}/{MAX_RETRIES}] Error: {e}")
                if attempt == MAX_RETRIES:
                    return {"status": "error", "modified_files": [], "commands": [], "logs": str(e)}

        return {"status": "error", "modified_files": [], "commands": [], "logs": "All retries exhausted"}
