# Multi-Phase Execution Design

**Date:** 2026-04-12  
**Status:** Approved  

---

## Overview

Extend the hybrid agentic pipeline with explicit cognitive phases:
`brainstorm → spec → plan → execute → review`

Brainstorm and spec are new. Plan, execute, and review already exist.
All phases go through a single centralized `_call_model(phase, prompt)` method
that enforces model routing and budget-aware fallback to local models.

---

## Goals

1. Add brainstorm and spec phases before planning — Claude enriches the planner's context with intent analysis and structured requirements.
2. Introduce phase-based model routing — each phase is mapped to either Claude or local.
3. Implement proactive budget-gating — switch to local at 80% of configured budget to avoid hitting Claude's limit mid-session.
4. Keep all existing behavior unchanged — new phases are opt-in via `ENABLE_PHASES=true`.

---

## Architecture

### Phase Pipeline

```
Orchestrator.run(user_input, phases=True)
  │
  ├─ _brainstorm(user_input)         → BrainstormResult (JSON)
  ├─ _spec(user_input, brainstorm)   → SpecResult (JSON)
  ├─ Planner.plan(user_input, ...)   → Plan (JSON)   [enriched with brainstorm+spec context]
  ├─ parallel Executor.run(step)     → per step      [unchanged]
  └─ ClaudeClient.review(result)     → review        [unchanged, gated by ENABLE_REVIEWER]
```

### Model Routing

All phase calls go through `_call_model(phase, prompt)` on `Orchestrator`.

| Phase      | Default model | Fallback |
|------------|---------------|----------|
| brainstorm | claude        | local    |
| spec       | claude        | local    |
| plan       | claude        | local (already exists in Planner) |
| execute    | local         | — |
| review     | claude        | — (skipped on failure) |

`route_phase(phase: str) -> str` is added to `core/router.py`. Returns `"claude"` or `"local"`.

### Budget-Aware Fallback

Inside `_call_model()`, before every Claude call:

1. Read `get_tracker()._claude_cost_usd` (or `_claude_input` if cost is always 0).
2. If `spent >= budget * threshold` → downgrade to local, log `[budget] threshold hit`.
3. If Claude call raises a rate-limit error → permanently downgrade for session, log `[budget] rate limited`.

The local model receives the same prompt as Claude would have — it just produces a lower-quality brainstorm/spec, which is acceptable given the constraint.

---

## Structured Outputs

### BrainstormResult

```json
{
  "intent": "string",
  "approaches": [
    {
      "name": "string",
      "description": "string",
      "trade_offs": "string"
    }
  ],
  "ambiguities": ["string"],
  "recommended_approach": "string"
}
```

### SpecResult

```json
{
  "requirements": ["string"],
  "constraints": ["string"],
  "expected_outputs": ["string"],
  "out_of_scope": ["string"]
}
```

Both use `validate_brainstorm()` and `validate_spec()` helpers (added to `core/validator.py`)
to enforce structure before passing forward.

### Plan (existing, unchanged)

```json
{
  "goal": "string",
  "steps": [
    {
      "id": 1,
      "description": "string",
      "files": [],
      "actions": [],
      "expected_output": "string",
      "depends_on": []
    }
  ],
  "constraints": []
}
```

---

## Prompts

### Brainstorm System Prompt

```
You are a brainstorming agent.

Analyze the user's goal and return ONLY valid JSON with this exact schema:

{
  "intent": string,
  "approaches": [{"name": string, "description": string, "trade_offs": string}],
  "ambiguities": string[],
  "recommended_approach": string
}

Rules:
- intent: what the user actually wants to achieve (1-2 sentences)
- approaches: 2-4 concrete implementation options with honest trade-offs
- ambiguities: open questions that would affect the implementation if answered differently
- recommended_approach: the name from approaches[] you would choose and why (1-2 sentences)
- Output ONLY the JSON object. No explanations, no markdown fences.
```

### Spec System Prompt

```
You are a spec-writing agent.

Given the brainstorm analysis below, produce a precise specification.
Return ONLY valid JSON with this exact schema:

{
  "requirements": string[],
  "constraints": string[],
  "expected_outputs": string[],
  "out_of_scope": string[]
}

Rules:
- requirements: concrete, testable statements of what must be true
- constraints: technical or environmental limits that shape the solution
- expected_outputs: what "done" looks like — files, behaviours, test results
- out_of_scope: explicitly excluded to prevent scope creep
- Output ONLY the JSON object. No explanations, no markdown fences.

Brainstorm context:
{brainstorm_json}
```

---

## Configuration

New env vars (added to `config/settings.py`):

| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_PHASES` | `false` | Enable brainstorm + spec phases |
| `CLAUDE_COST_BUDGET_USD` | `0.0` | Budget cap in USD (0 = unlimited) |
| `CLAUDE_TOKEN_BUDGET` | `0` | Budget cap in input tokens (0 = unlimited; used when cost tracking returns 0) |
| `CLAUDE_BUDGET_THRESHOLD` | `0.80` | Route to local when spent ≥ budget × threshold |

---

## Files Changed

| File | Change |
|---|---|
| `core/orchestrator.py` | Add `_brainstorm()`, `_spec()`, `_call_model()`; gate in `run()` |
| `core/router.py` | Add `route_phase(phase)` function |
| `models/claude_client.py` | Add `brainstorm()` and `spec()` methods with structured prompts |
| `core/validator.py` | Add `validate_brainstorm()` and `validate_spec()` |
| `config/settings.py` | Add `ENABLE_PHASES`, `CLAUDE_COST_BUDGET_USD`, `CLAUDE_TOKEN_BUDGET`, `CLAUDE_BUDGET_THRESHOLD` |

**No other files modified.** `Executor`, `LocalClient`, `main.py`, `bench.py` are untouched.

---

## Out of Scope

- Saving/resuming brainstorm or spec output (only plan is resumed)
- Per-phase token budgets (one shared budget for all Claude phases)
- Streaming output for brainstorm/spec phases
- Changing the local model prompt format for brainstorm/spec (same prompt, best-effort)
