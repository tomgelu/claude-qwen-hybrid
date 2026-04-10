import os
from models.claude_client import ClaudeClient
from core.validator import validate_plan
from config.settings import get_workspace


class Planner:
    def __init__(self):
        self.client = ClaudeClient()

    def plan(self, user_input: str) -> dict:
        workspace = get_workspace()
        ws_context = self._workspace_context(workspace)
        raw_plan = self.client.get_plan(user_input, ws_context)
        return validate_plan(raw_plan)

    def _workspace_context(self, workspace: str) -> str:
        try:
            entries = sorted(os.listdir(workspace))
            top_level = ", ".join(entries[:60])
            return f"\n\nWorkspace: {workspace}\nTop-level contents: {top_level}"
        except Exception:
            return f"\n\nWorkspace: {workspace}"
