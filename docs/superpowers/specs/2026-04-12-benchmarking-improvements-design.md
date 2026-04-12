# Benchmarking Improvements — Design Spec

**Date:** 2026-04-12  
**Scope:** Option B — Extended metrics + task suite (no structural rewrite)  
**Goal:** Make both RTK token savings and overall pipeline health first-class, measured with statistical validity

---

## 1. Bug Fixes (prerequisites)

These two bugs corrupt current measurements and must be fixed before any new metrics are added.

### 1.1 Shared plan for RTK A/B runs

**Problem:** `bench.py` and `benchmark.py::run_rtk_pair` invoke the Claude planner independently for each RTK run. The plan structure (step count, ordering, wording) varies between runs, so the Qwen turn count varies independently of RTK. The A/B delta is not clean.

**Fix:** Add `Orchestrator.run_with_plan(plan, ...)` that skips the planning step and executes a pre-supplied plan dict. The benchmark runner calls the planner once, captures the plan, then passes it to both the RTK-off and RTK-on runs.

```python
# benchmark.py / bench.py
plan = planner.plan(task)
stats_off = run_once(plan=plan, use_rtk=False, workspace=ws_a)
stats_on  = run_once(plan=plan, use_rtk=True,  workspace=ws_b)
```

```python
# core/orchestrator.py
def run_with_plan(self, plan: dict, dry_run=False, resume=False) -> dict:
    """Execute a pre-generated plan, skipping the planning step."""
    ...
```

### 1.2 Token tracker reset bug

**Problem:** `bench.py` resets the tracker with `tt_mod.tracker = tt_mod.TokenTracker()`, but `orchestrator.py` captures the old object at import time via `from utils.token_tracker import tracker as _tracker`. The module reload doesn't retarget already-bound names, so measurements from run B accumulate on top of run A.

**Fix:** Replace the module-level singleton pattern with a `get_tracker()` accessor. All callers use `get_tracker()` at call time instead of binding `tracker` at import time. Reset becomes `tt_mod._tracker = tt_mod.TokenTracker()`.

```python
# utils/token_tracker.py
_tracker = TokenTracker()

def get_tracker() -> TokenTracker:
    return _tracker
```

All callers change from `from utils.token_tracker import tracker as _tracker` to `from utils.token_tracker import get_tracker` and call `get_tracker()` at the point of use.

---

## 2. Extended Metrics

### 2.1 Latency breakdown (TTFT + generation time)

**Where:** `models/local_client.py::_call_streaming()`

Record two timestamps per call:
- `ttft_s` — wall seconds from request send until first non-empty content delta arrives
- `generation_s` — total wall seconds for the full streaming response

Accumulate per-turn in the agent loop. After the loop, the tracker exposes:
- `ttft_min`, `ttft_mean`, `ttft_max`
- `generation_mean`, `generation_total`

These are recorded in JSONL for pipeline runs. For chat prompts in `benchmark.py`, `latency_s` already captures end-to-end time — add `ttft_s` to the per-prompt record.

**Tracker additions:**
```python
ttft_samples: list[float] = []
generation_samples: list[float] = []
```

### 2.2 Per-tool context bytes

**Where:** `models/local_client.py::run_agent_loop()`, both native and XML branches

**Problem:** `tool_response_bytes` is a single int — no visibility into which tools generate the most context bloat.

**Fix:** Expand to `tool_bytes_by_name: dict[str, int]`. Every tool result append adds `len(result_str)` to `tool_bytes_by_name[fn_name]` in addition to the existing total accumulator (keep the total for backwards compatibility).

**JSONL addition:** `"tool_bytes_by_name": {"run_command": 12400, "read_file": 3200, ...}`

This is the most actionable RTK insight: if `run_command` accounts for 80% of tool bytes, that's exactly what RTK targets.

### 2.3 Context trim events

**Where:** `models/local_client.py::_trim_messages()`

Currently trims silently. Add two counters to the tracker:
- `trim_events: int` — how many times `_trim_messages` actually truncated at least one message
- `trim_bytes_saved: int` — total bytes removed by truncation

**Why:** If trim events are high, the task is hitting context pressure. That's a signal to tune `_TRIM_KEEP_TURNS` or to split the task into smaller steps in the planner.

### 2.4 Retry and reviewer overhead

**Where:** `core/orchestrator.py::_run_step_with_retry()`

The orchestrator already counts retry attempts. Surface them:
- `retry_count: int` — total retries across all steps
- `reviewer_calls: int` — total reviewer invocations (only nonzero when `ENABLE_REVIEWER=true`)

Add these to the pipeline JSONL record. Makes the token cost of retries and review visible for tuning `MAX_RETRIES`.

---

## 3. Task Suite

Replace the single `fibonacci` pipeline task with four tasks that cover distinct workload shapes. All tasks are defined in a `PIPELINE_TASKS` list in `benchmark.py`. Each task runs as an RTK pair (same shared plan, RTK off then on).

| ID | Description | Key tools exercised | Expected turns |
|----|-------------|---------------------|----------------|
| `fibonacci` | Create fib.py CLI + test_fib.py, run tests | `write_file`, `run_command`, `run_tests` | ~5 |
| `multifile_refactor` | Split a monolithic Python file into two modules, update imports | `read_file`, `write_file`, `replace_lines`, `search_files` | ~10 |
| `test_writer` | Given an implementation file, write a pytest suite covering edge cases | `read_file`, `write_file`, `run_tests` | ~8 |
| `git_workflow` | Make a small targeted change, stage, commit with message, show diff | `read_file`, `replace_lines`, `git_commit`, `git_diff`, `git_status` | ~5 |

**Task fixture approach:** Each task gets a `setup` callable that creates the necessary starting files in the workspace before the pipeline runs. `fibonacci` and `git_workflow` need no setup. `multifile_refactor` and `test_writer` need a seed file written first.

**Timeout:** Increase pipeline timeout from 120s/150s to 240s to accommodate the longer-turn tasks.

---

## 4. Viewer Updates

Three new charts added to `bench_viewer.py`. All use the existing Chart.js setup.

### 4.1 Per-tool context bytes stacked bar
- One bar group per run
- Stacked by tool name (color per tool)
- Shows which tools dominate context usage and how RTK affects each

### 4.2 Context trim events over runs
- Line chart, x = run timestamp, y = trim_events count
- Secondary y = trim_bytes_saved
- Surfaces whether tasks are hitting context pressure trends over time

### 4.3 Latency breakdown per model
- Grouped bar: TTFT vs generation time for chat prompts
- Separate from pipeline runs (chat prompts have more reliable latency samples)

### 4.4 Per-task RTK savings table
In the existing RTK savings table, add a `task_id` column so savings from `fibonacci`, `multifile_refactor`, `test_writer`, and `git_workflow` are shown as separate rows rather than collapsed into a single pipeline entry per run.

---

## 5. Data Schema Changes

The JSONL format gains new optional fields (backwards-compatible — old readers ignore unknown keys):

```jsonc
// pipeline runs
{
  "run_id": "...",
  "task_id": "fibonacci",          // NEW: which task
  "ttft_mean_s": 0.42,             // NEW: mean TTFT across turns
  "generation_total_s": 18.3,      // NEW: total generation time
  "tool_bytes_by_name": {          // NEW: per-tool breakdown
    "run_command": 12400,
    "read_file": 3200,
    "git_status": 180
  },
  "trim_events": 2,                // NEW
  "trim_bytes_saved": 4800,        // NEW
  "retry_count": 1,                // NEW
  "reviewer_calls": 0,             // NEW
  // existing fields unchanged...
}

// chat prompt runs — add ttft_s
{
  "ttft_s": 0.38,                  // NEW
  // existing fields unchanged...
}
```

---

## 6. File Change Summary

| File | Change |
|------|--------|
| `utils/token_tracker.py` | Add `get_tracker()`, per-tool bytes dict, TTFT samples, trim counters, retry/reviewer counters |
| `models/local_client.py` | Use `get_tracker()`, add TTFT/gen timing, per-tool bytes, trim event counting |
| `core/orchestrator.py` | Add `run_with_plan()`, surface retry/reviewer counts |
| `benchmark.py` | Use shared plan for RTK pairs, add PIPELINE_TASKS suite, record new fields, per-task savings table |
| `bench.py` | Use `run_with_plan()`, use `get_tracker()` reset, add `--runs N` flag for averaging |
| `bench_viewer.py` | Add 3 new charts, per-task savings table, TTFT latency display |

No new files. No changes to `tools/`, `config/`, `core/planner.py`, or `core/executor.py`.

---

## 7. Out of Scope

- Statistical significance testing (p-values, confidence intervals) — single-digit sample sizes make this misleading
- Automated benchmark scheduling (cron)
- Quality/correctness scoring of agent outputs
- Cost estimation for local model runs (no pricing data available)
