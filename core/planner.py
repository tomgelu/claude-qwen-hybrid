import json
import os
from models.claude_client import ClaudeClient
from core.validator import validate_plan
from config.settings import get_workspace
from utils.logger import get_logger

log = get_logger(__name__)


class Planner:
    def __init__(self):
        self.client = ClaudeClient()
        self.claude_available = True  # 🔥 runtime flag

    def plan(self, user_input: str, brainstorm: dict = None, spec: dict = None) -> dict:
        workspace = get_workspace()
        ws_context = self._workspace_context(workspace)

        # Append brainstorm and spec context if provided by the phase pipeline
        if brainstorm is not None:
            ws_context += f'\n\nBrainstorm analysis:\n{json.dumps(brainstorm, indent=2)}'
        if spec is not None:
            ws_context += f'\n\nSpec:\n{json.dumps(spec, indent=2)}'
        # 🔥 Try Claude ONLY if still available
        if self.claude_available:
            try:
                raw_plan = self.client.get_plan(user_input, ws_context)
                log.info("[planner] Using Claude planner")
                return validate_plan(raw_plan)

            except Exception as e:
                log.warning(f"[planner] Claude unavailable: {e}")
                log.info("[planner] Disabling Claude and falling back to local planning")
                self.claude_available = False  # 🔥 permanently disable for session

        # 🔥 Fallback (Qwen will handle everything)
        return self._fallback_plan(user_input)

    def _workspace_context(self, workspace: str) -> str:
        try:
            entries = sorted(os.listdir(workspace))
            top_level = ", ".join(entries[:60])
            return f"\n\nWorkspace: {workspace}\nTop-level contents: {top_level}"
        except Exception:
            return f"\n\nWorkspace: {workspace}"

    def _fallback_plan(self, user_input: str) -> dict:
        return {
            "goal": user_input,
            "steps": [
                {
                    "id": 1,
                    "description": user_input,
                    "depends_on": [],
                }
            ],
            "constraints": [],
        }