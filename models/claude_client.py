import json
import re
import subprocess
from config.settings import CLAUDE_MODEL

PLANNER_SYSTEM_PROMPT = """You are a planning agent.

You MUST output ONLY valid JSON.
Do NOT include explanations.

Follow this schema exactly:

{
  "goal": string,
  "steps": [
    {
      "id": number,
      "description": string,
      "files": string[],
      "actions": string[],
      "expected_output": string,
      "depends_on": number[]
    }
  ],
  "constraints": string[]
}

Rules:
- Each step must be atomic
- Be explicit about files — use paths relative to the workspace
- Set depends_on to the IDs of steps that must succeed before this one; empty array if none
- Steps with no shared files or conflicting actions can have empty depends_on (they are independent)
- Avoid ambiguity
- Do not skip steps"""

REVIEWER_SYSTEM_PROMPT = """You are a code reviewer.

Analyze the result of the given execution step and return ONLY valid JSON:

{
  "issues": string[],
  "improvements": string[],
  "validation": "pass" | "fail",
  "summary": string
}

Set validation to "fail" only if there are correctness bugs, test failures, or missing required behaviour.
Style or minor improvements alone should not cause a "fail"."""

BRAINSTORM_SYSTEM_PROMPT = """You are a brainstorming agent.

Analyze the user goal and return ONLY valid JSON with this exact schema:

{
  "intent": string,
  "approaches": [{"name": string, "description": string, "trade_offs": string}],
  "ambiguities": [string],
  "recommended_approach": string
}

Rules:
- intent: what the user actually wants to achieve (1-2 sentences)
- approaches: 2-4 concrete implementation options with honest trade-offs
- ambiguities: open questions that would affect implementation if answered differently
- recommended_approach: the name from approaches[] you would choose and why (1-2 sentences)
- Output ONLY the JSON object. No explanations, no markdown fences."""

SPEC_SYSTEM_PROMPT = """You are a spec-writing agent.

Given the brainstorm analysis in the user message, produce a precise specification.
Return ONLY valid JSON with this exact schema:

{
  "requirements": [string],
  "constraints": [string],
  "expected_outputs": [string],
  "out_of_scope": [string]
}

Rules:
- requirements: concrete, testable statements of what must be true
- constraints: technical or environmental limits that shape the solution
- expected_outputs: what "done" looks like — files, behaviours, test results
- out_of_scope: explicitly excluded to prevent scope creep
- Output ONLY the JSON object. No explanations, no markdown fences."""


def _strip_json_fences(raw: str) -> str:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def _call_claude(system_prompt: str, user_message: str, model: str) -> str:
    result = subprocess.run(
        [
            "claude",
            "--print",
            "--model", model,
            "--system-prompt", system_prompt,
            "--output-format", "json",
            user_message,
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=120,  # planning calls can take 30-60s
    )

    output = result.stdout.strip() + "\n" + result.stderr.strip()

    # 🔥 CRITICAL: detect rate limit / quota / CLI block
    if "You've hit your limit" in output or "rate limit" in output.lower():
        raise RuntimeError("Claude rate limited")

    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error: {result.stderr.strip()}")

    # Try parsing structured output
    try:
        wrapper = json.loads(result.stdout)

        usage = wrapper.get("usage", {})
        from utils.token_tracker import get_tracker
        get_tracker().add_claude(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read=usage.get("cache_read_input_tokens", 0),
            cache_write=usage.get("cache_creation_input_tokens", 0),
            cost_usd=wrapper.get("total_cost_usd", 0.0),
        )

        text_output = wrapper.get("result", "")

    except (json.JSONDecodeError, KeyError):
        # 🔥 fallback: raw output (might still be valid JSON string)
        text_output = result.stdout

    cleaned = _strip_json_fences(text_output)

    # 🔥 FINAL SAFETY: ensure it's valid JSON
    try:
        json.loads(cleaned)
    except Exception:
        raise RuntimeError("Claude returned invalid JSON")

    return cleaned


class ClaudeClient:
    def __init__(self):
        self.model = CLAUDE_MODEL
        self.enabled = True  # 🔥 runtime disable

    def get_plan(self, user_input: str, workspace_context: str = "") -> dict:
        if not self.enabled:
            raise RuntimeError("Claude disabled")

        user_message = f"User goal:\n{user_input}{workspace_context}"

        try:
            raw = _call_claude(PLANNER_SYSTEM_PROMPT, user_message, self.model)
            return json.loads(raw)

        except Exception as e:
            self.enabled = False  # 🔥 disable permanently
            raise RuntimeError(f"Claude planner failed: {e}")

    def review(self, execution_result: dict) -> dict:
        if not self.enabled:
            raise RuntimeError("Claude disabled")

        user_message = f"Analyze the result of this step:\n{json.dumps(execution_result, indent=2)}"

        try:
            raw = _call_claude(REVIEWER_SYSTEM_PROMPT, user_message, self.model)
            return json.loads(raw)

        except Exception as e:
            self.enabled = False  # 🔥 disable permanently
            raise RuntimeError(f"Claude reviewer failed: {e}")

    def call(self, system_prompt: str, user_message: str) -> dict:
        """Generic structured call — used by phase runner for brainstorm/spec."""
        if not self.enabled:
            raise RuntimeError("Claude disabled")
        try:
            raw = _call_claude(system_prompt, user_message, self.model)
            return json.loads(raw)
        except Exception as e:
            self.enabled = False  # 🔥 disable permanently
            raise RuntimeError(f"Claude call failed: {e}")

    def brainstorm(self, user_input: str) -> dict:
        """Run the brainstorm phase — returns structured BrainstormResult."""
        if not self.enabled:
            raise RuntimeError("Claude disabled")
        try:
            raw = _call_claude(BRAINSTORM_SYSTEM_PROMPT, f"User goal:\n{user_input}", self.model)
            return json.loads(raw)
        except Exception as e:
            self.enabled = False  # 🔥 disable permanently
            raise RuntimeError(f"Claude brainstorm failed: {e}")

    def spec(self, user_input: str, brainstorm_result: dict) -> dict:
        """Run the spec phase — returns structured SpecResult."""
        if not self.enabled:
            raise RuntimeError("Claude disabled")
        msg = f"User goal:\n{user_input}\n\nBrainstorm:\n{json.dumps(brainstorm_result, indent=2)}"
        try:
            raw = _call_claude(SPEC_SYSTEM_PROMPT, msg, self.model)
            return json.loads(raw)
        except Exception as e:
            self.enabled = False  # 🔥 disable permanently
            raise RuntimeError(f"Claude spec failed: {e}")
