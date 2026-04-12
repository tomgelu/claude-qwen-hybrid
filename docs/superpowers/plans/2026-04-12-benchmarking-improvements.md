# Benchmarking Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two measurement bugs that corrupt current RTK A/B data, add richer per-tool/latency/trim/retry metrics, replace the trivial fibonacci task with four substantive pipeline tasks, and surface the new data in the viewer.

**Architecture:** All changes are additive or small modifications to six existing files. No new files. The tracker gains a `get_tracker()` accessor (fixes the reset bug); the orchestrator gains `run_with_plan()` (fixes the shared-plan bug); benchmark.py gains a PIPELINE_TASKS registry with setup callables; bench_viewer.py gains three new Chart.js charts.

**Tech Stack:** Python 3.11+, requests (SSE streaming), Chart.js 4.4 (viewer), pytest (task fixtures), git subprocess (git_audit fixture)

---

## File Map

| File | Change |
|------|--------|
| `utils/token_tracker.py` | Add `get_tracker()`, per-tool bytes dict, TTFT/gen samples, trim counters, retry/reviewer counters |
| `models/local_client.py` | Use `get_tracker()` everywhere; add TTFT timing; per-tool bytes; trim event counting |
| `core/orchestrator.py` | Add `plan` param to `run()` to skip planner; surface retry/reviewer counts into tracker |
| `benchmark.py` | Shared plan for RTK pairs; PIPELINE_TASKS suite; record new JSONL fields; per-task savings |
| `bench.py` | Use shared plan; fix tracker reset; add `--runs N` flag with averaging |
| `bench_viewer.py` | Per-tool stacked bar; trim events line chart; TTFT grouped bar; per-task savings table |

---

## Task 1: Rewrite utils/token_tracker.py

**Files:**
- Modify: `utils/token_tracker.py`

- [ ] **Step 1: Replace the file with the new tracker**

```python
# utils/token_tracker.py
from __future__ import annotations


class TokenTracker:
    def __init__(self):
        self._claude_input = 0
        self._claude_output = 0
        self._claude_cache_read = 0
        self._claude_cache_write = 0
        self._claude_cost_usd = 0.0
        self._qwen_input = 0
        self._qwen_output = 0
        # Total bytes of tool results fed back into Qwen context (kept for backwards compat)
        self.tool_response_bytes = 0
        # Per-tool breakdown: {"run_command": 12400, "read_file": 3200, ...}
        self.tool_bytes_by_name: dict[str, int] = {}
        # Time-to-first-token and generation time per streaming call (seconds)
        self.ttft_samples: list[float] = []
        self.generation_samples: list[float] = []
        # Context trimming
        self.trim_events: int = 0        # calls to _trim_messages that truncated ≥1 message
        self.trim_bytes_saved: int = 0   # total bytes removed by truncation
        # Retry / reviewer overhead
        self.retry_count: int = 0        # total retries across all steps
        self.reviewer_calls: int = 0     # total reviewer invocations

    def add_claude(self, input_tokens: int = 0, output_tokens: int = 0,
                   cache_read: int = 0, cache_write: int = 0, cost_usd: float = 0.0):
        self._claude_input += input_tokens
        self._claude_output += output_tokens
        self._claude_cache_read += cache_read
        self._claude_cache_write += cache_write
        self._claude_cost_usd += cost_usd

    def add_qwen(self, input_tokens: int = 0, output_tokens: int = 0):
        self._qwen_input += input_tokens
        self._qwen_output += output_tokens

    def add_tool_bytes(self, tool_name: str, byte_count: int):
        """Record bytes injected into context for a named tool result."""
        self.tool_response_bytes += byte_count
        self.tool_bytes_by_name[tool_name] = (
            self.tool_bytes_by_name.get(tool_name, 0) + byte_count
        )

    def add_ttft(self, ttft_s: float, generation_s: float):
        """Record time-to-first-token and total generation time for one call."""
        self.ttft_samples.append(ttft_s)
        self.generation_samples.append(generation_s)

    def has_data(self) -> bool:
        return (self._claude_input + self._claude_output +
                self._qwen_input + self._qwen_output) > 0

    def summary(self) -> str:
        lines = ["[tokens] ── Usage Summary ──────────────────────────"]
        lines.append(
            f"[tokens] Claude (cloud):  {self._claude_input:>7,} in / {self._claude_output:>6,} out"
            + (f"  |  {self._claude_cache_read:,} cache-read / {self._claude_cache_write:,} cache-write"
               if self._claude_cache_read or self._claude_cache_write else "")
            + f"  |  ${self._claude_cost_usd:.4f}"
        )
        qwen_total = self._qwen_input + self._qwen_output
        lines.append(
            f"[tokens] Qwen  (local):   {self._qwen_input:>7,} in / {self._qwen_output:>6,} out"
            + f"  |  {qwen_total:,} total"
        )
        if self.tool_response_bytes:
            lines.append(
                f"[tokens] Tool resp bytes: {self.tool_response_bytes:>7,}  (context bloat)"
            )
            if self.tool_bytes_by_name:
                top = sorted(self.tool_bytes_by_name.items(), key=lambda x: -x[1])[:5]
                lines.append("[tokens]   by tool: " + "  ".join(f"{k}={v:,}" for k, v in top))
        if self.trim_events:
            lines.append(
                f"[tokens] Trim events: {self.trim_events}  saved {self.trim_bytes_saved:,} bytes"
            )
        if self.retry_count or self.reviewer_calls:
            lines.append(
                f"[tokens] Retries: {self.retry_count}  Reviewer calls: {self.reviewer_calls}"
            )
        if self.ttft_samples:
            mean_ttft = sum(self.ttft_samples) / len(self.ttft_samples)
            lines.append(
                f"[tokens] TTFT: min={min(self.ttft_samples):.2f}s  "
                f"mean={mean_ttft:.2f}s  max={max(self.ttft_samples):.2f}s"
            )
        lines.append("[tokens] ────────────────────────────────────────────")
        return "\n".join(lines)


_tracker = TokenTracker()


def get_tracker() -> TokenTracker:
    """Return the current active tracker. All callers use this instead of importing
    `tracker` directly so that benchmark resets (reassigning _tracker) take effect."""
    return _tracker
```

- [ ] **Step 2: Verify the module loads cleanly**

```bash
cd ~/claude-autonaumous
python3 -c "from utils.token_tracker import get_tracker; t = get_tracker(); t.add_tool_bytes('run_command', 100); print(t.tool_bytes_by_name)"
```

Expected output: `{'run_command': 100}`

- [ ] **Step 3: Commit**

```bash
git add utils/token_tracker.py
git commit -m "feat(tracker): add get_tracker(), per-tool bytes, TTFT, trim and retry counters"
```

---

## Task 2: Fix tracker imports in models/local_client.py

**Files:**
- Modify: `models/local_client.py` (import line + all `_tracker.` call sites)

The current file imports `from utils.token_tracker import tracker as _tracker`. This binds to the old object at import time, so benchmark resets don't work. Replace every use with `get_tracker()`.

- [ ] **Step 1: Update the import line**

Find line 7:
```python
from utils.token_tracker import tracker as _tracker
```
Replace with:
```python
from utils.token_tracker import get_tracker
```

- [ ] **Step 2: Update _call_streaming() — usage line ~108**

Find:
```python
                _tracker.add_qwen(
                    input_tokens=u.get("prompt_tokens", 0),
                    output_tokens=u.get("completion_tokens", 0),
                )
```
Replace with:
```python
                get_tracker().add_qwen(
                    input_tokens=u.get("prompt_tokens", 0),
                    output_tokens=u.get("completion_tokens", 0),
                )
```

- [ ] **Step 3: Update _call() non-streaming fallback — usage ~173**

Find:
```python
        if usage:
            _tracker.add_qwen(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            )
```
Replace with:
```python
        if usage:
            get_tracker().add_qwen(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            )
```

- [ ] **Step 4: Update tool bytes in run_agent_loop() — native branch (~line 238)**

Find (first occurrence, inside `if native_tool_calls:` block):
```python
                    _tracker.tool_response_bytes += len(result_str.encode())
```
Replace with:
```python
                    get_tracker().add_tool_bytes(fn_name, len(result_str.encode()))
```

- [ ] **Step 5: Update tool bytes in run_agent_loop() — XML fallback branch (~line 259)**

Find (second occurrence, inside `else:` XML block):
```python
                    _tracker.tool_response_bytes += len(result_str.encode())
```
Replace with:
```python
                    get_tracker().add_tool_bytes(fn_name, len(result_str.encode()))
```

- [ ] **Step 6: Verify no remaining _tracker references**

```bash
grep -n "_tracker" models/local_client.py
```

Expected: no output (zero matches).

- [ ] **Step 7: Commit**

```bash
git add models/local_client.py
git commit -m "fix(local_client): use get_tracker() to fix tracker reset bug"
```

---

## Task 3: Fix tracker import in core/orchestrator.py

**Files:**
- Modify: `core/orchestrator.py` (import line + usage site)

- [ ] **Step 1: Update import on line 12**

Find:
```python
from utils.token_tracker import tracker as _tracker
```
Replace with:
```python
from utils.token_tracker import get_tracker
```

- [ ] **Step 2: Update summary call at end of run() (~line 192)**

Find:
```python
        if _tracker.has_data():
            log.info("\n" + _tracker.summary())
```
Replace with:
```python
        if get_tracker().has_data():
            log.info("\n" + get_tracker().summary())
```

- [ ] **Step 3: Verify no remaining _tracker references**

```bash
grep -n "_tracker" core/orchestrator.py
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add core/orchestrator.py
git commit -m "fix(orchestrator): use get_tracker() to fix tracker reset bug"
```

---

## Task 4: Add TTFT timing to models/local_client.py

**Files:**
- Modify: `models/local_client.py`

Add `import time` at the top and capture TTFT + generation time inside `_call_streaming()`.

- [ ] **Step 1: Add `import time` at the top of the file**

Find the existing imports block (around line 1-6). Add after the last import:
```python
import time
```

- [ ] **Step 2: Add TTFT capture inside _call_streaming()**

The method starts a request but currently has no timing. Modify `_call_streaming` to look like this (show only the changed portions — add the 5 marked lines):

```python
    def _call_streaming(self, payload: dict) -> tuple[str, list[dict] | None]:
        payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
        _t_start = time.perf_counter()          # NEW
        resp = requests.post(self.url, json=payload, timeout=self.timeout, stream=True)
        resp.raise_for_status()

        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        printed_any = False
        _ttft_s: float | None = None            # NEW

        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if chunk.get("usage"):
                u = chunk["usage"]
                get_tracker().add_qwen(
                    input_tokens=u.get("prompt_tokens", 0),
                    output_tokens=u.get("completion_tokens", 0),
                )

            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})

            if delta.get("content"):
                tok = delta["content"]
                if _ttft_s is None:             # NEW
                    _ttft_s = time.perf_counter() - _t_start   # NEW
                content_parts.append(tok)
                print(tok, end="", flush=True)
                printed_any = True

            for tc in delta.get("tool_calls", []):
                idx = tc.get("index", 0)
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                if tc.get("id"):
                    tool_calls_acc[idx]["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    tool_calls_acc[idx]["name"] += fn["name"]
                if fn.get("arguments"):
                    tool_calls_acc[idx]["arguments"] += fn["arguments"]

        if printed_any:
            print()

        _generation_s = time.perf_counter() - _t_start         # NEW
        if _ttft_s is not None:                                 # NEW
            get_tracker().add_ttft(_ttft_s, _generation_s)     # NEW

        full_content = "".join(content_parts)
        # ... rest of method unchanged
```

- [ ] **Step 3: Verify the method still has the correct return value unchanged**

The last lines of `_call_streaming` should still be:
```python
        if tool_calls_acc:
            tool_calls = [
                {
                    "id": v["id"] or f"stream_{k}",
                    "type": "function",
                    "function": {"name": v["name"], "arguments": v["arguments"]},
                }
                for k, v in sorted(tool_calls_acc.items())
            ]
            return full_content, tool_calls

        return full_content, None
```

- [ ] **Step 4: Commit**

```bash
git add models/local_client.py
git commit -m "feat(local_client): track TTFT and generation time per streaming call"
```

---

## Task 5: Add trim event counting to models/local_client.py

**Files:**
- Modify: `models/local_client.py` (`_trim_messages` function, lines ~15-39)

- [ ] **Step 1: Modify _trim_messages to count trim events**

Replace the inner loop body in `_trim_messages`:

**Before:**
```python
    cutoff = tool_indices[-_TRIM_KEEP_TURNS]  # compress everything before this index
    trimmed = []
    for i, m in enumerate(messages):
        if i < cutoff and m.get("role") == "tool":
            content = m.get("content", "")
            if len(content) > _TRIM_MAX_BYTES:
                m = {**m, "content": content[:_TRIM_MAX_BYTES] + " …[trimmed]"}
        trimmed.append(m)
    return trimmed
```

**After:**
```python
    cutoff = tool_indices[-_TRIM_KEEP_TURNS]  # compress everything before this index
    trimmed = []
    _did_trim = False
    for i, m in enumerate(messages):
        if i < cutoff and m.get("role") == "tool":
            content = m.get("content", "")
            if len(content) > _TRIM_MAX_BYTES:
                get_tracker().trim_bytes_saved += len(content) - _TRIM_MAX_BYTES
                _did_trim = True
                m = {**m, "content": content[:_TRIM_MAX_BYTES] + " …[trimmed]"}
        trimmed.append(m)
    if _did_trim:
        get_tracker().trim_events += 1
    return trimmed
```

- [ ] **Step 2: Commit**

```bash
git add models/local_client.py
git commit -m "feat(local_client): count trim events and bytes saved in _trim_messages"
```

---

## Task 6: Add run_with_plan() and retry/reviewer metrics to core/orchestrator.py

**Files:**
- Modify: `core/orchestrator.py`

### Part A — run_with_plan()

Add a `plan` parameter to `run()` so callers can pass a pre-generated plan dict and skip the planner. This is the fix for the RTK A/B shared-plan bug.

- [ ] **Step 1: Add `plan` parameter to run() signature**

Find:
```python
    def run(self, user_input: str, dry_run: bool = False, resume: bool = False) -> dict:
```
Replace with:
```python
    def run(self, user_input: str, dry_run: bool = False, resume: bool = False,
            plan: dict | None = None) -> dict:
```

- [ ] **Step 2: Skip planner when plan is supplied**

Find the block that starts with:
```python
        if resume:
            saved = _load_plan()
```

Before that block, add this early-exit guard so a supplied plan bypasses both resume loading and the planner call:

```python
        # ── Use pre-supplied plan (skips planner — used by benchmark for shared A/B plans) ─
        if plan is not None:
            log.info(f"[orchestrator] Using pre-supplied plan: {plan['goal']}")
            step_statuses: dict[str, str] = {}
            # fall through directly to the execution section below
        else:
```

Then indent the entire existing `if resume: ... if not resume: plan = self.planner.plan(...)` block under the `else:` branch. The result should look like:

```python
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
```

### Part B — surface retry and reviewer counts

- [ ] **Step 3: Increment retry counter in _run_step_with_retry()**

In `_run_step_with_retry`, find the `max_turns` retry block:
```python
                if result["status"] == "max_turns":
                    log.warning(...)
                    prior_attempt = result
                    if attempt == MAX_RETRIES:
                        result["status"] = "error"
                    continue
```
Add `get_tracker().retry_count += 1` inside:
```python
                if result["status"] == "max_turns":
                    get_tracker().retry_count += 1
                    log.warning(...)
                    prior_attempt = result
                    if attempt == MAX_RETRIES:
                        result["status"] = "error"
                    continue
```

- [ ] **Step 4: Increment reviewer counter and retry counter for failed reviews**

Find:
```python
                if result["status"] == "success" and self.reviewer:
                    review = self.reviewer.review(result)
                    result["review"] = review
                    log.info(f"  [review] {review.get('validation', 'N/A')}: {review.get('summary', '')}")
                    if review.get("validation") == "fail" and attempt < MAX_RETRIES:
                        issues = "; ".join(review.get("issues", []))
                        log.warning(f"  [retry {attempt}/{MAX_RETRIES}] review failed: {issues}")
                        prior_attempt = result
                        continue
```
Replace with:
```python
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
```

- [ ] **Step 5: Verify the module imports correctly**

```bash
python3 -c "from core.orchestrator import Orchestrator; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add core/orchestrator.py
git commit -m "feat(orchestrator): add plan param to run(), surface retry/reviewer metrics"
```

---

## Task 7: Update bench.py — shared plan, tracker reset fix, --runs flag

**Files:**
- Modify: `bench.py`

- [ ] **Step 1: Replace the top of bench.py (imports + TASK + run_once signature)**

Replace everything from the top of the file through the end of the `run_once` function with:

```python
#!/usr/bin/env python3
"""
bench.py — compare pipeline token usage with and without RTK.

Runs the same task twice using the SAME Claude plan in identical fresh workspaces:
  - Run A: USE_RTK=false  (raw command output into Qwen context)
  - Run B: USE_RTK=true   (RTK-filtered output)

Prints a side-by-side comparison of Qwen token counts and context bloat.
With --runs N, runs N A/B pairs and reports averages.

Usage:
    python3 bench.py
    python3 bench.py "your task here"
    python3 bench.py --runs 3
    python3 bench.py "your task" --runs 5
"""

import argparse
import os
import sys
import shutil
import tempfile
import importlib
import threading

DEFAULT_TASK = (
    "Build a Python CLI tool in csv_stats.py that reads a CSV file and computes "
    "per-column statistics (count, mean, median, stddev, null count), then writes "
    "a Markdown summary to --output. Accept --input and --output flags. "
    "Add tests in test_csv_stats.py for normal data, empty column, all-null column, "
    "and single-row CSV. Run the tests."
)


def _fresh_modules():
    """Blow away all cached imports from this project so tracker resets cleanly."""
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith(("core.", "models.", "tools.", "utils.", "config.")):
            del sys.modules[mod_name]
    importlib.invalidate_caches()


def _reset_tracker():
    """Replace the module-level tracker with a fresh one.
    Must be called AFTER _fresh_modules() so all callers get the new object via get_tracker()."""
    import utils.token_tracker as tt_mod
    tt_mod._tracker = tt_mod.TokenTracker()


def run_once(label: str, use_rtk: bool, workspace: str, plan: dict) -> dict:
    """Run the full pipeline in workspace using a pre-supplied plan. Returns token stats."""
    os.environ["USE_RTK"] = "true" if use_rtk else "false"
    os.environ["WORKSPACE_DIR"] = workspace
    os.environ["STREAM_OUTPUT"] = "false"

    _fresh_modules()
    _reset_tracker()

    from core.orchestrator import Orchestrator
    from utils.token_tracker import get_tracker
    orch = Orchestrator()

    print(f"\n{'='*60}")
    print(f"  RUN {label}  |  USE_RTK={use_rtk}  |  workspace={workspace}")
    print(f"{'='*60}", flush=True)

    RUN_TIMEOUT = 240
    exc_holder = []

    def _run():
        try:
            orch.run("", plan=plan)
        except Exception as e:
            exc_holder.append(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=RUN_TIMEOUT)
    if t.is_alive():
        print(f"\n  [bench] RUN {label} timed out after {RUN_TIMEOUT}s — partial results only",
              flush=True)
    if exc_holder:
        print(f"\n  [bench] RUN {label} error: {exc_holder[0]}", flush=True)

    tr = get_tracker()
    return {
        "label": label,
        "use_rtk": use_rtk,
        "qwen_in":    tr._qwen_input,
        "qwen_out":   tr._qwen_output,
        "tool_bytes": tr.tool_response_bytes,
        "claude_in":  tr._claude_input,
        "claude_out": tr._claude_output,
    }
```

- [ ] **Step 2: Replace the main() function**

```python
def _average_stats(stats_list: list[dict]) -> dict:
    """Average numeric fields across multiple runs."""
    if not stats_list:
        return {}
    keys = ["qwen_in", "qwen_out", "tool_bytes", "claude_in", "claude_out"]
    avg = {**stats_list[0]}
    for key in keys:
        avg[key] = int(sum(s[key] for s in stats_list) / len(stats_list))
    return avg


def main():
    parser = argparse.ArgumentParser(description="RTK A/B token benchmark")
    parser.add_argument("task", nargs="?", default=None, help="Task description")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of A/B pairs to run and average (default: 1)")
    args = parser.parse_args()

    task = args.task or DEFAULT_TASK

    base = tempfile.mkdtemp(prefix="bench_")
    print(f"Task: {task[:80]}{'…' if len(task) > 80 else ''}", flush=True)
    print(f"Runs: {args.runs}  Workspaces: {base}/", flush=True)

    # Generate the plan ONCE before any module reloads — it's just a dict, survives reloads
    _fresh_modules()
    from core.planner import Planner
    print("Planning...", flush=True)
    shared_plan = Planner().plan(task)
    print(f"Plan: {shared_plan['goal']} ({len(shared_plan['steps'])} steps)", flush=True)

    all_a: list[dict] = []
    all_b: list[dict] = []

    try:
        for run_n in range(1, args.runs + 1):
            suffix = f"_{run_n}" if args.runs > 1 else ""
            ws_a = os.path.join(base, f"run_a{suffix}")
            ws_b = os.path.join(base, f"run_b{suffix}")
            os.makedirs(ws_a)
            os.makedirs(ws_b)

            if args.runs > 1:
                print(f"\n── Run {run_n}/{args.runs} ──", flush=True)

            stats_a = run_once(f"A{suffix} (no RTK)", use_rtk=False,
                               workspace=ws_a, plan=shared_plan)
            stats_b = run_once(f"B{suffix} (RTK)   ", use_rtk=True,
                               workspace=ws_b, plan=shared_plan)
            all_a.append(stats_a)
            all_b.append(stats_b)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    avg_a = _average_stats(all_a)
    avg_b = _average_stats(all_b)
    label_a = f"A (no RTK){f' avg×{args.runs}' if args.runs > 1 else ''}"
    label_b = f"B (RTK)   {f' avg×{args.runs}' if args.runs > 1 else ''}"

    print("\n")
    print("╔══════════════════════════════════════════════════════════╗")
    print("║              RTK BENCHMARK RESULTS                      ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print(f"║  Task: {task[:50]:<50} ║")
    print("╠════════════════════════╦═══════════════╦════════════════╣")
    print(f"║ Metric                 ║ {label_a:^13} ║ {label_b:^14} ║")
    print("╠════════════════════════╬═══════════════╬════════════════╣")

    def row(label, a_val, b_val):
        diff = b_val - a_val
        pct = (diff / a_val * 100) if a_val else 0
        sign = "▼" if diff < 0 else ("▲" if diff > 0 else " ")
        change = f"{sign}{abs(pct):.1f}%"
        print(f"║ {label:<22} ║ {a_val:>13,} ║ {b_val:>11,}  {change:>4} ║")

    row("Qwen input tokens",    avg_a["qwen_in"],    avg_b["qwen_in"])
    row("Qwen output tokens",   avg_a["qwen_out"],   avg_b["qwen_out"])
    row("Tool resp bytes",      avg_a["tool_bytes"], avg_b["tool_bytes"])
    row("Claude input tokens",  avg_a["claude_in"],  avg_b["claude_in"])
    row("Claude output tokens", avg_a["claude_out"], avg_b["claude_out"])

    print("╚════════════════════════╩═══════════════╩════════════════╝")

    if avg_a["qwen_in"] and avg_b["qwen_in"]:
        saved = avg_a["qwen_in"] - avg_b["qwen_in"]
        pct = saved / avg_a["qwen_in"] * 100
        print(f"\n  RTK saved {saved:,} Qwen input tokens ({pct:.1f}%)")
    if avg_a["tool_bytes"] and avg_b["tool_bytes"]:
        saved_b = avg_a["tool_bytes"] - avg_b["tool_bytes"]
        pct_b = saved_b / avg_a["tool_bytes"] * 100
        print(f"  RTK reduced context bloat by {saved_b:,} bytes ({pct_b:.1f}%)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify bench.py --help works**

```bash
python3 bench.py --help
```

Expected: usage message showing `--runs` flag with no import errors.

- [ ] **Step 4: Commit**

```bash
git add bench.py
git commit -m "fix(bench): shared plan for A/B runs, fix tracker reset, add --runs N averaging"
```

---

## Task 8: Add PIPELINE_TASKS and seed fixtures to benchmark.py

**Files:**
- Modify: `benchmark.py`

This task adds the four pipeline task definitions and their setup callables at the top of `benchmark.py`, just after the `PROMPTS` list.

- [ ] **Step 1: Add setup functions and PIPELINE_TASKS after the PROMPTS list (~line 69)**

Insert after the closing `]` of `PROMPTS`:

```python

# ── Pipeline task suite ───────────────────────────────────────────────────────
# Tasks are deliberately non-trivial so the agent must reason, read, and
# navigate the workspace rather than recall a memorized answer.

def _setup_multifile_refactor(workspace: str) -> None:
    from pathlib import Path
    ws = Path(workspace)

    (ws / "store.py").write_text(
        '# store.py — monolithic inventory manager\n'
        'import json\nimport os\nimport sys\n'
        'from dataclasses import dataclass, asdict\nfrom typing import Optional\n\n'
        '@dataclass\nclass Item:\n'
        '    id: int\n    name: str\n    quantity: int\n    price: float\n'
        '    category: Optional[str] = None\n\n'
        '@dataclass\nclass Store:\n'
        '    name: str\n    items: list\n\n'
        '    def add_item(self, item): self.items.append(item)\n\n'
        '    def remove_item(self, item_id):\n'
        '        self.items = [i for i in self.items if i.id != item_id]\n\n'
        '    def find_item(self, item_id):\n'
        '        return next((i for i in self.items if i.id == item_id), None)\n\n'
        '    def total_value(self):\n'
        '        return sum(i.quantity * i.price for i in self.items)\n\n'
        '    def items_by_category(self, category):\n'
        '        return [i for i in self.items if i.category == category]\n\n'
        'STORE_FILE = "store_data.json"\n\n'
        'def save_store(store, path=STORE_FILE):\n'
        '    data = {"name": store.name, "items": [asdict(i) for i in store.items]}\n'
        '    with open(path, "w") as f: json.dump(data, f, indent=2)\n\n'
        'def load_store(path=STORE_FILE):\n'
        '    if not os.path.exists(path): return Store(name="My Store", items=[])\n'
        '    with open(path) as f: data = json.load(f)\n'
        '    return Store(name=data["name"], items=[Item(**i) for i in data["items"]])\n\n'
        'def cmd_add(args):\n'
        '    store = load_store()\n'
        '    item = Item(id=len(store.items)+1, name=args[0], quantity=int(args[1]),\n'
        '                price=float(args[2]), category=args[3] if len(args)>3 else None)\n'
        '    store.add_item(item)\n    save_store(store)\n'
        '    print(f"Added: {item.name} x{item.quantity} @ ${item.price:.2f}")\n\n'
        'def cmd_remove(args):\n'
        '    store = load_store()\n    store.remove_item(int(args[0]))\n'
        '    save_store(store)\n    print(f"Removed item {args[0]}")\n\n'
        'def cmd_list(args):\n'
        '    store = load_store()\n'
        '    if not store.items: print("No items."); return\n'
        '    for i in store.items:\n'
        '        cat = f" [{i.category}]" if i.category else ""\n'
        '        print(f"  {i.id:3d}  {i.name:<20} x{i.quantity:4d}  ${i.price:8.2f}{cat}")\n'
        '    print(f"  Total value: ${store.total_value():.2f}")\n\n'
        'def cmd_show(args):\n'
        '    store = load_store()\n    item = store.find_item(int(args[0]))\n'
        '    if item: print(f"Item {item.id}: {item.name}, qty={item.quantity}")\n'
        '    else: print(f"Item {args[0]} not found")\n\n'
        'COMMANDS = {"add": cmd_add, "remove": cmd_remove, "list": cmd_list, "show": cmd_show}\n\n'
        'def main():\n'
        '    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:\n'
        '        print(f"Usage: python store.py <{\'|\'.join(COMMANDS)}> [args...]")\n'
        '        sys.exit(1)\n'
        '    COMMANDS[sys.argv[1]](sys.argv[2:])\n\n'
        'if __name__ == "__main__":\n    main()\n'
    )

    (ws / "test_store.py").write_text(
        'import pytest\nfrom store import Item, Store, save_store, load_store\n'
        'import os, tempfile\n\n'
        'def test_add(): s=Store("t",[]); s.add_item(Item(1,"A",1,1.0)); assert len(s.items)==1\n'
        'def test_remove(): s=Store("t",[Item(1,"A",1,1.0)]); s.remove_item(1); assert s.items==[]\n'
        'def test_total(): s=Store("t",[Item(1,"A",2,3.0),Item(2,"B",1,5.0)]); assert s.total_value()==11.0\n'
        'def test_category():\n'
        '    s=Store("t",[Item(1,"A",1,1.0,category="fruit"),Item(2,"B",1,1.0,category="veg")])\n'
        '    assert len(s.items_by_category("fruit"))==1\n'
        'def test_roundtrip():\n'
        '    with tempfile.NamedTemporaryFile(suffix=".json",delete=False) as f: path=f.name\n'
        '    try:\n'
        '        s=Store("Shop",[Item(1,"W",10,2.99)])\n'
        '        save_store(s,path); loaded=load_store(path)\n'
        '        assert loaded.name=="Shop" and loaded.items[0].name=="W"\n'
        '    finally: os.unlink(path)\n'
    )


def _setup_bug_hunt(workspace: str) -> None:
    from pathlib import Path
    ws = Path(workspace)

    (ws / "server.py").write_text(
        '# server.py — simple in-memory task API with 3 injected bugs\n'
        'import json\n\n'
        '_tasks: list[dict] = []\n_next_id = 1\n\n\n'
        'def get_tasks(page: int = 1, per_page: int = 10) -> list[dict]:\n'
        '    """Return a page of tasks (1-indexed)."""\n'
        '    start = (page - 1) * per_page\n'
        '    end = start + per_page + 1  # BUG 1: off-by-one, should be start + per_page\n'
        '    return _tasks[start:end]\n\n\n'
        'def get_task(task_id: int) -> dict | None:\n'
        '    return next((t for t in _tasks if t["id"] == task_id), None)\n\n\n'
        'def create_task(title: str, done: bool = False) -> dict:\n'
        '    global _next_id\n'
        '    # BUG 2: no input sanitization — title accepted without stripping whitespace\n'
        '    task = {"id": _next_id, "title": title, "done": done}\n'
        '    _tasks.append(task)\n    _next_id += 1\n    return task\n\n\n'
        'def update_task(task_id: int, **kwargs) -> dict | None:\n'
        '    task = get_task(task_id)\n'
        '    if task is None: return None\n'
        '    task.update(kwargs)\n    return task\n\n\n'
        'def delete_task(task_id: int) -> bool:\n'
        '    global _tasks\n    before = len(_tasks)\n'
        '    _tasks = [t for t in _tasks if t["id"] != task_id]\n'
        '    return len(_tasks) < before\n\n\n'
        'def not_found_status() -> int:\n'
        '    return 200  # BUG 3: should return 404\n'
    )


def _setup_git_audit(workspace: str) -> None:
    """Create a small git repo with 5 commits, the last introducing a broken import."""
    import subprocess
    from pathlib import Path
    ws = Path(workspace)

    def git(*args):
        subprocess.run(["git"] + list(args), cwd=workspace,
                       check=True, capture_output=True)

    git("init")
    git("config", "user.email", "bench@test.local")
    git("config", "user.name", "Bench")

    # Commit 1: initial utils
    (ws / "utils.py").write_text(
        'def format_timestamp(ts: float) -> str:\n'
        '    from datetime import datetime\n'
        '    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")\n\n'
        'def clamp(value, lo, hi):\n'
        '    return max(lo, min(hi, value))\n'
    )
    git("add", "utils.py")
    git("commit", "-m", "feat: add utils module")

    # Commit 2: add config
    (ws / "config.py").write_text(
        'MAX_RETRIES = 3\nDEFAULT_TIMEOUT = 30\nDEBUG = False\n'
    )
    git("add", "config.py")
    git("commit", "-m", "feat: add config defaults")

    # Commit 3: add app skeleton
    (ws / "app.py").write_text(
        'from utils import format_timestamp, clamp\nfrom config import MAX_RETRIES\n\n'
        'def run(value: float) -> str:\n'
        '    v = clamp(value, 0, 100)\n'
        '    return f"[{format_timestamp(0)}] processed {v}"\n'
    )
    git("add", "app.py")
    git("commit", "-m", "feat: initial app.py")

    # Commit 4: fix clamp edge case
    (ws / "utils.py").write_text(
        'def format_timestamp(ts: float) -> str:\n'
        '    from datetime import datetime\n'
        '    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")\n\n'
        'def clamp(value, lo, hi):\n'
        '    if lo > hi: raise ValueError(f"lo={lo} > hi={hi}")\n'
        '    return max(lo, min(hi, value))\n'
    )
    git("add", "utils.py")
    git("commit", "-m", "fix: clamp raises on invalid range")

    # Commit 5: refactor app — introduce broken import (format_date doesn't exist)
    (ws / "app.py").write_text(
        'from utils import format_date, clamp  # BUG: format_date should be format_timestamp\n'
        'from config import MAX_RETRIES\n\n'
        'def run(value: float) -> str:\n'
        '    v = clamp(value, 0, 100)\n'
        '    return f"[{format_date(0)}] processed {v}"\n'
    )
    git("add", "app.py")
    git("commit", "-m", "chore: rename timestamp helper (incomplete)")


PIPELINE_TASKS = [
    {
        "id": "csv_pipeline",
        "description": (
            "Build a Python CLI tool in csv_stats.py that reads a CSV file and computes "
            "per-column statistics (count, mean, median, stddev, null count), writing a "
            "Markdown summary report. Accept --input and --output flags. "
            "Add tests in test_csv_stats.py covering: normal data, empty column, "
            "all-null column, single-row CSV. Run the tests."
        ),
        "setup": None,
        "timeout": 240,
    },
    {
        "id": "multifile_refactor",
        "description": (
            "store.py is a monolithic inventory manager. Refactor it by splitting into "
            "three modules: models.py (Item and Store dataclasses), storage.py (save_store "
            "and load_store), and cli.py (cmd_* functions and main). Update all imports. "
            "All existing tests in test_store.py must still pass after the split."
        ),
        "setup": _setup_multifile_refactor,
        "timeout": 240,
    },
    {
        "id": "bug_hunt",
        "description": (
            "server.py has three bugs: an off-by-one in get_tasks() pagination, missing "
            "input sanitization in create_task() (title should be stripped), and "
            "not_found_status() returning 200 instead of 404. Find and fix all three, "
            "then add a targeted test for each fix in test_server.py. Run the tests."
        ),
        "setup": _setup_bug_hunt,
        "timeout": 240,
    },
    {
        "id": "git_audit",
        "description": (
            "This git repo has 5 commits. Examine the last 3 commits and write a "
            "CHANGELOG.md entry grouping the changes by type (feat/fix/chore). "
            "Then fix the broken import introduced in the most recent commit in app.py "
            "(it imports format_date which does not exist — check utils.py to find the "
            "correct name), and commit the fix."
        ),
        "setup": _setup_git_audit,
        "timeout": 240,
    },
]
```

- [ ] **Step 2: Verify the setup functions run without error**

```bash
python3 -c "
import tempfile, os, sys
sys.path.insert(0, '.')
from benchmark import _setup_multifile_refactor, _setup_bug_hunt, _setup_git_audit
import tempfile, shutil

for name, fn in [('multifile_refactor', _setup_multifile_refactor),
                 ('bug_hunt', _setup_bug_hunt),
                 ('git_audit', _setup_git_audit)]:
    ws = tempfile.mkdtemp()
    try:
        fn(ws)
        print(f'{name}: OK — {os.listdir(ws)}')
    except Exception as e:
        print(f'{name}: FAIL — {e}')
    finally:
        shutil.rmtree(ws)
"
```

Expected: three `OK` lines with file listings.

- [ ] **Step 3: Commit**

```bash
git add benchmark.py
git commit -m "feat(benchmark): add PIPELINE_TASKS suite with 4 non-trivial tasks and seed fixtures"
```

---

## Task 9: Update run_rtk_pair() and recording in benchmark.py

**Files:**
- Modify: `benchmark.py`

Replace `run_rtk_pair()` to use the shared plan, iterate over `PIPELINE_TASKS`, and record `task_id` plus the new metric fields in JSONL.

- [ ] **Step 1: Replace run_rtk_pair()**

Find and replace the entire `run_rtk_pair` function (lines ~145–239):

```python
def run_rtk_pair(run_id: str, timestamp: str) -> list[dict]:
    """
    For each task in PIPELINE_TASKS, run the full Claude→Qwen pipeline twice
    using the SAME Claude plan: once with USE_RTK=false, once with USE_RTK=true.
    Returns result dicts for recording.
    """
    import importlib
    import shutil
    import tempfile
    import threading

    results = []
    base = tempfile.mkdtemp(prefix="bench_rtk_")

    try:
        for task_def in PIPELINE_TASKS:
            task_id   = task_def["id"]
            task_desc = task_def["description"]
            setup_fn  = task_def["setup"]
            timeout   = task_def["timeout"]

            print(f"\n  [pipeline] task={task_id}")

            # Generate shared plan ONCE before module reloads
            for mod in list(sys.modules.keys()):
                if mod.startswith(("core.", "models.", "tools.", "utils.", "config.")):
                    del sys.modules[mod]
            importlib.invalidate_caches()

            from core.planner import Planner
            print(f"    planning... ", end="", flush=True)
            shared_plan = Planner().plan(task_desc)
            print(f"{len(shared_plan['steps'])} steps", flush=True)

            for use_rtk in (False, True):
                label = "rtk_on" if use_rtk else "rtk_off"
                ws = os.path.join(base, f"{task_id}_{label}")
                os.makedirs(ws, exist_ok=True)

                # Run seed setup if needed
                if setup_fn:
                    try:
                        setup_fn(ws)
                    except Exception as e:
                        print(f"    setup failed: {e}")
                        results.append({
                            "run_id": run_id, "timestamp": timestamp,
                            "model_type": "pipeline", "model": LOCAL_MODEL_NAME,
                            "task_id": task_id,
                            "prompt_id": f"pipeline_{label}_{task_id}",
                            "prompt_desc": f"RTK pipeline / {task_id}",
                            "use_rtk": use_rtk,
                            "error": f"setup failed: {e}",
                            "latency_s": 0.0,
                        })
                        continue

                os.environ["USE_RTK"]       = "true" if use_rtk else "false"
                os.environ["WORKSPACE_DIR"] = ws
                os.environ["STREAM_OUTPUT"] = "false"

                # Fresh modules + fresh tracker
                for mod in list(sys.modules.keys()):
                    if mod.startswith(("core.", "models.", "tools.", "utils.", "config.")):
                        del sys.modules[mod]
                importlib.invalidate_caches()

                import utils.token_tracker as tt
                tt._tracker = tt.TokenTracker()

                from core.orchestrator import Orchestrator
                from utils.token_tracker import get_tracker
                orch = Orchestrator()

                sys.stdout.write(f"    {label:<7} ... ")
                sys.stdout.flush()

                start = time.perf_counter()
                exc = []

                def _run():
                    try:
                        orch.run("", plan=shared_plan)
                    except Exception as e:
                        exc.append(e)

                t = threading.Thread(target=_run, daemon=True)
                t.start()
                t.join(timeout=timeout)
                elapsed = time.perf_counter() - start

                tr = get_tracker()

                if t.is_alive():
                    print(f"timeout after {int(elapsed)}s")
                    results.append({
                        "run_id": run_id, "timestamp": timestamp,
                        "model_type": "pipeline", "model": LOCAL_MODEL_NAME,
                        "task_id": task_id,
                        "prompt_id": f"pipeline_{label}_{task_id}",
                        "prompt_desc": f"RTK pipeline / {task_id}",
                        "use_rtk": use_rtk,
                        "error": f"timeout after {int(elapsed)}s",
                        "latency_s": round(elapsed, 2),
                    })
                    continue

                if exc:
                    print(f"error: {exc[0]}")

                ttft_mean = (sum(tr.ttft_samples) / len(tr.ttft_samples)
                             if tr.ttft_samples else 0.0)
                gen_total = sum(tr.generation_samples)

                print(
                    f"qwen {tr._qwen_input:,}in/{tr._qwen_output:,}out  "
                    f"tool={tr.tool_response_bytes:,}B  "
                    f"trim={tr.trim_events}  retry={tr.retry_count}  "
                    f"{int(elapsed)}s"
                )

                results.append({
                    "run_id":        run_id,
                    "timestamp":     timestamp,
                    "model_type":    "pipeline",
                    "model":         LOCAL_MODEL_NAME,
                    "task_id":       task_id,
                    "prompt_id":     f"pipeline_{label}_{task_id}",
                    "prompt_desc":   f"RTK pipeline / {task_id}",
                    "use_rtk":       use_rtk,
                    "input_tokens":  tr._qwen_input,
                    "output_tokens": tr._qwen_output,
                    "tool_bytes":    tr.tool_response_bytes,
                    "tool_bytes_by_name": dict(tr.tool_bytes_by_name),
                    "claude_input_tokens":  tr._claude_input,
                    "claude_output_tokens": tr._claude_output,
                    "ttft_mean_s":    round(ttft_mean, 3),
                    "generation_total_s": round(gen_total, 2),
                    "trim_events":    tr.trim_events,
                    "trim_bytes_saved": tr.trim_bytes_saved,
                    "retry_count":    tr.retry_count,
                    "reviewer_calls": tr.reviewer_calls,
                    "latency_s":      round(elapsed, 2),
                })

    finally:
        shutil.rmtree(base, ignore_errors=True)

    return results
```

- [ ] **Step 2: Update write_report() to show per-task savings**

Find the RTK savings section inside `write_report()`:

```python
        if savings_rows:
            lines += [
                "",
                "**RTK savings (no-RTK minus RTK):**",
                "",
                "| Run | Model | Qwen input Δ | Tool bytes Δ |",
                "|-----|-------|--------------|--------------|",
                *savings_rows,
            ]
```

Replace the `pairs` building logic and savings section with:

```python
        # Pair up runs by (run_id, task_id) and show savings per task
        pairs: dict[tuple, dict] = {}
        for e in pipeline_entries:
            key = (e["run_id"], e.get("task_id", "unknown"))
            pairs.setdefault(key, {})[e.get("use_rtk")] = e

        savings_rows = []
        for (rid, tid), pair in pairs.items():
            if False in pair and True in pair:
                off, on = pair[False], pair[True]
                in_saved  = off["input_tokens"] - on["input_tokens"]
                in_pct    = in_saved / off["input_tokens"] * 100 if off["input_tokens"] else 0
                tb_saved  = off.get("tool_bytes", 0) - on.get("tool_bytes", 0)
                tb_pct    = tb_saved / off["tool_bytes"] * 100 if off.get("tool_bytes") else 0
                savings_rows.append(
                    f"| {rid} | {tid} | `{off['model']}` "
                    f"| {in_saved:+,} ({in_pct:+.1f}%) "
                    f"| {tb_saved:+,} ({tb_pct:+.1f}%) |"
                )

        if savings_rows:
            lines += [
                "",
                "**RTK savings per task (no-RTK minus RTK):**",
                "",
                "| Run | Task | Model | Qwen input Δ | Tool bytes Δ |",
                "|-----|------|-------|--------------|--------------|",
                *savings_rows,
            ]
```

Also update the per-run table header to include Task column:

Find in the pipeline section of `write_report()`:
```python
            "| Run | Model | RTK | Qwen in | Qwen out | Tool bytes | Claude out | Time |",
            "|-----|-------|-----|---------|----------|------------|------------|------|",
```
Replace with:
```python
            "| Run | Task | Model | RTK | Qwen in | Qwen out | Tool bytes | Time |",
            "|-----|------|-------|-----|---------|----------|------------|------|",
```

And update the row formatter immediately after:
```python
        for e in pipeline_entries:
            rtk = "✓" if e.get("use_rtk") else "✗"
            lines.append(
                f"| {e['run_id']} | {e.get('task_id','—')} | `{e['model']}` | {rtk} "
                f"| {e['input_tokens']:,} | {e['output_tokens']:,} "
                f"| {e.get('tool_bytes', 0):,} "
                f"| {int(e['latency_s'])}s |"
            )
```

- [ ] **Step 3: Verify benchmark.py --show runs without error**

```bash
python3 benchmark.py --show
```

Expected: existing results print without errors; report regenerated.

- [ ] **Step 4: Commit**

```bash
git add benchmark.py
git commit -m "feat(benchmark): shared plan for RTK pairs, record new metrics, per-task savings table"
```

---

## Task 10: Add per-tool bytes and trim charts to bench_viewer.py

**Files:**
- Modify: `bench_viewer.py`

- [ ] **Step 1: Add `task_id` column to RTK table header in HTML**

Find in the HTML string:
```html
      <table id="rtk-table"><thead><tr>
        <th>Run</th><th>Model</th><th>RTK</th>
        <th>Qwen in</th><th>Qwen out</th><th>Tool bytes</th><th>Time</th>
      </tr></thead><tbody id="rtk-body"></tbody></table>
```
Replace with:
```html
      <table id="rtk-table"><thead><tr>
        <th>Run</th><th>Task</th><th>Model</th><th>RTK</th>
        <th>Qwen in</th><th>Qwen out</th><th>Tool bytes</th><th>Trim</th><th>Retry</th><th>Time</th>
      </tr></thead><tbody id="rtk-body"></tbody></table>
```

- [ ] **Step 2: Update renderRtk table body rows in JavaScript**

Find in the JavaScript:
```javascript
    tr.innerHTML = `
      <td class="run-label">${r.run_id}</td>
      <td class="mono" style="font-size:.78rem">${r.model}</td>
      <td>${r.use_rtk ? '<span class="rtk-on">✓ on</span>' : '<span class="rtk-off">✗ off</span>'}</td>
      <td>${fmt(r.input_tokens)}</td>
      <td>${fmt(r.output_tokens)}</td>
      <td>${fmt(r.tool_bytes)}</td>
      <td>${Math.round(r.latency_s)}s</td>`;
```
Replace with:
```javascript
    tr.innerHTML = `
      <td class="run-label">${r.run_id}</td>
      <td class="mono" style="font-size:.78rem">${r.task_id || '—'}</td>
      <td class="mono" style="font-size:.78rem">${r.model}</td>
      <td>${r.use_rtk ? '<span class="rtk-on">✓ on</span>' : '<span class="rtk-off">✗ off</span>'}</td>
      <td>${fmt(r.input_tokens)}</td>
      <td>${fmt(r.output_tokens)}</td>
      <td>${fmt(r.tool_bytes)}</td>
      <td>${r.trim_events ?? '—'}</td>
      <td>${r.retry_count ?? '—'}</td>
      <td>${Math.round(r.latency_s)}s</td>`;
```

- [ ] **Step 3: Add per-tool stacked bar chart section to HTML**

After the closing `</section>` of the RTK section, add a new section:
```html
  <section id="tool-bytes-section">
    <h2>Tool Context Bytes by Type</h2>
    <div class="charts" id="tool-bytes-charts"></div>
  </section>
  <section id="trim-section">
    <h2>Context Trim Events</h2>
    <div class="charts" id="trim-charts"></div>
  </section>
```

- [ ] **Step 4: Add renderToolBytes() and renderTrimChart() functions to JavaScript**

Add before the closing `</script>` tag:

```javascript
const TOOL_COLORS = {
  run_command: 'rgba(248,113,113,.75)',
  read_file:   'rgba(134,239,172,.75)',
  write_file:  'rgba(125,211,252,.75)',
  search_files:'rgba(216,180,254,.75)',
  git_status:  'rgba(253,224,71,.75)',
  git_diff:    'rgba(251,146,60,.75)',
  git_commit:  'rgba(167,243,208,.75)',
  replace_lines:'rgba(196,181,253,.75)',
  list_directory:'rgba(147,197,253,.75)',
  run_tests:   'rgba(110,231,183,.75)',
  glob_files:  'rgba(249,168,212,.75)',
};
const DEFAULT_TOOL_COLOR = 'rgba(107,114,128,.6)';

function renderToolBytes(pipeline) {
  charts.forEach(c => c.destroy && c.id === 'tool-bytes' && c.destroy());
  const div = document.getElementById('tool-bytes-charts');
  div.innerHTML = '';

  const runs = pipeline.filter(r => r.tool_bytes_by_name);
  if (!runs.length) {
    div.innerHTML = '<p class="empty">No per-tool breakdown recorded yet — run benchmark.py after updating.</p>';
    return;
  }

  // Collect all tool names seen
  const allTools = [...new Set(runs.flatMap(r => Object.keys(r.tool_bytes_by_name || {})))];
  const labels = runs.map(r => `${r.run_id.replace(/^(\d{4})(\d{2})(\d{2})_/, '$1-$2-$3 ')}\n${r.task_id||''} ${r.use_rtk ? '✓RTK' : '✗RTK'}`);

  const datasets = allTools.map(tool => ({
    label: tool,
    data: runs.map(r => (r.tool_bytes_by_name || {})[tool] || 0),
    backgroundColor: TOOL_COLORS[tool] || DEFAULT_TOOL_COLOR,
    borderRadius: 3,
  }));

  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';
  wrap.style.flex = '2';
  wrap.innerHTML = '<h3>Bytes fed into context per tool (stacked)</h3><canvas></canvas>';
  div.appendChild(wrap);

  const c = new Chart(wrap.querySelector('canvas'), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      scales: {
        x: { stacked: true, ticks: { color: '#6b7280', font: { size: 9 } }, grid: { color: '#1e1e2e' } },
        y: { stacked: true, ticks: { color: '#6b7280', font: { size: 10 } }, grid: { color: '#1e1e2e' } },
      },
      plugins: {
        legend: { labels: { color: '#9ca3af', font: { size: 10 }, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: ctx => ` ${ctx.dataset.label}: ${Number(ctx.parsed.y).toLocaleString()} B`
          }
        }
      }
    }
  });
  c.id = 'tool-bytes';
  charts.push(c);
}

function renderTrimChart(pipeline) {
  const div = document.getElementById('trim-charts');
  div.innerHTML = '';

  const runs = pipeline.filter(r => r.trim_events != null);
  if (!runs.length) {
    div.innerHTML = '<p class="empty">No trim event data yet.</p>';
    return;
  }

  const labels = runs.map(r =>
    `${r.run_id.replace(/^(\d{4})(\d{2})(\d{2})_/, '$1-$2-$3 ')} ${r.task_id||''} ${r.use_rtk?'✓':'✗'}`
  );

  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';
  wrap.style.flex = '1';
  wrap.innerHTML = '<h3>Trim events &amp; bytes saved</h3><canvas></canvas>';
  div.appendChild(wrap);

  new Chart(wrap.querySelector('canvas'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Trim events', data: runs.map(r => r.trim_events || 0),
          backgroundColor: 'rgba(167,243,208,.75)', yAxisID: 'y', borderRadius: 3 },
        { label: 'Bytes saved', data: runs.map(r => r.trim_bytes_saved || 0),
          backgroundColor: 'rgba(216,180,254,.5)', yAxisID: 'y2', borderRadius: 3 },
      ]
    },
    options: {
      responsive: true,
      scales: {
        x: { ticks: { color: '#6b7280', font: { size: 9 } }, grid: { color: '#1e1e2e' } },
        y:  { ticks: { color: '#86efac', font: { size: 9 } }, grid: { color: '#1e1e2e' } },
        y2: { position: 'right', ticks: { color: '#d8b4fe', font: { size: 9 } }, grid: { display: false } },
      },
      plugins: { legend: { labels: { color: '#9ca3af', font: { size: 10 }, boxWidth: 12 } } }
    }
  });
}
```

- [ ] **Step 5: Wire renderToolBytes and renderTrimChart into render()**

Find:
```javascript
  renderRtk(pipeline);
  renderChat(chat);
```
Replace with:
```javascript
  renderRtk(pipeline);
  renderToolBytes(pipeline);
  renderTrimChart(pipeline);
  renderChat(chat);
```

- [ ] **Step 6: Verify viewer starts without JS errors**

```bash
python3 bench_viewer.py &
sleep 1
curl -s http://localhost:8080 | grep -c "chart-wrap"
kill %1
```

Expected: a number ≥ 1 (HTML served, chart-wrap divs present).

- [ ] **Step 7: Commit**

```bash
git add bench_viewer.py
git commit -m "feat(viewer): add per-tool bytes stacked bar and trim events chart"
```

---

## Task 11: Add TTFT latency chart and update savings table in bench_viewer.py

**Files:**
- Modify: `bench_viewer.py`

- [ ] **Step 1: Add TTFT section HTML after trim section**

After the `trim-section` closing `</section>`, add:
```html
  <section id="ttft-section">
    <h2>Latency — TTFT &amp; Generation Time (chat prompts)</h2>
    <div class="charts" id="ttft-charts"></div>
  </section>
```

- [ ] **Step 2: Add renderTtft() function before closing </script>**

```javascript
function renderTtft(chat) {
  const div = document.getElementById('ttft-charts');
  div.innerHTML = '';

  const withTtft = chat.filter(r => r.ttft_s != null && !r.error);
  if (!withTtft.length) {
    div.innerHTML = '<p class="empty">No TTFT data yet — run benchmark.py after updating.</p>';
    return;
  }

  // Group by model
  const models = [...new Set(withTtft.map(r => r.model))];
  const prompts = [...new Set(withTtft.map(r => r.prompt_id))];

  for (const model of models) {
    const modelRows = withTtft.filter(r => r.model === model);
    const wrap = document.createElement('div');
    wrap.className = 'chart-wrap';
    wrap.innerHTML = `<h3>${model}</h3><canvas></canvas>`;
    div.appendChild(wrap);

    new Chart(wrap.querySelector('canvas'), {
      type: 'bar',
      data: {
        labels: prompts,
        datasets: [
          { label: 'TTFT (s)',
            data: prompts.map(p => {
              const r = modelRows.find(x => x.prompt_id === p);
              return r ? r.ttft_s : null;
            }),
            backgroundColor: 'rgba(125,211,252,.75)', borderRadius: 3 },
          { label: 'Total latency (s)',
            data: prompts.map(p => {
              const r = modelRows.find(x => x.prompt_id === p);
              return r ? r.latency_s : null;
            }),
            backgroundColor: 'rgba(248,113,113,.4)', borderRadius: 3 },
        ]
      },
      options: {
        responsive: true,
        scales: {
          x: { ticks: { color: '#6b7280', font: { size: 10 } }, grid: { color: '#1e1e2e' } },
          y: { ticks: { color: '#6b7280', font: { size: 10 } }, grid: { color: '#1e1e2e' } },
        },
        plugins: { legend: { labels: { color: '#9ca3af', font: { size: 10 }, boxWidth: 12 } } }
      }
    });
  }
}
```

- [ ] **Step 3: Wire renderTtft into render()**

Find:
```javascript
  renderRtk(pipeline);
  renderToolBytes(pipeline);
  renderTrimChart(pipeline);
  renderChat(chat);
```
Replace with:
```javascript
  renderRtk(pipeline);
  renderToolBytes(pipeline);
  renderTrimChart(pipeline);
  renderTtft(chat);
  renderChat(chat);
```

- [ ] **Step 4: Update savings table to show task column**

In `renderRtk`, find the savings table HTML:
```javascript
    sDiv.innerHTML = `<h3 style="font-size:.82rem;color:#6b7280;margin-bottom:.5rem">Savings (no-RTK → RTK)</h3>
      <table><thead><tr><th>Run</th><th>Qwen input Δ</th><th>Qwen output Δ</th><th>Tool bytes Δ</th></tr></thead>
      <tbody>${savingsRows}</tbody></table>`;
```
Replace with:
```javascript
    sDiv.innerHTML = `<h3 style="font-size:.82rem;color:#6b7280;margin-bottom:.5rem">RTK Savings per Task (no-RTK → RTK)</h3>
      <table><thead><tr><th>Run</th><th>Task</th><th>Qwen input Δ</th><th>Qwen output Δ</th><th>Tool bytes Δ</th></tr></thead>
      <tbody>${savingsRows}</tbody></table>`;
```

And update `pairList` grouping and savings row template in `renderRtk`:

Find:
```javascript
  const pairs = {};
  for (const r of rows) {
    pairs[r.run_id] = pairs[r.run_id] || {};
    pairs[r.run_id][r.use_rtk ? 'on' : 'off'] = r;
  }
  const pairList = Object.entries(pairs).filter(([, p]) => p.on && p.off);
```
Replace with (pair on run_id + task_id):
```javascript
  const pairs = {};
  for (const r of rows) {
    const key = `${r.run_id}||${r.task_id || ''}`;
    pairs[key] = pairs[key] || {};
    pairs[key][r.use_rtk ? 'on' : 'off'] = r;
  }
  const pairList = Object.entries(pairs).filter(([, p]) => p.on && p.off);
```

And update the savings row template in the `if (pairList.length)` block:
```javascript
      const savingsRows = pairList.map(([key, p]) => {
        const [rid, tid] = key.split('||');
        const inD  = p.off.input_tokens  - p.on.input_tokens;
        const outD = p.off.output_tokens - p.on.output_tokens;
        const tbD  = (p.off.tool_bytes || 0) - (p.on.tool_bytes || 0);
        return `<tr>
          <td class="run-label">${rid}</td>
          <td class="mono" style="font-size:.78rem">${tid || '—'}</td>
          <td>${delta(p.off.input_tokens,  p.on.input_tokens)  || fmt(inD)}</td>
          <td>${delta(p.off.output_tokens, p.on.output_tokens) || fmt(outD)}</td>
          <td>${delta(p.off.tool_bytes,    p.on.tool_bytes)    || fmt(tbD)}</td>
        </tr>`;
      }).join('');
```

- [ ] **Step 5: Final smoke test — viewer starts and serves HTML**

```bash
python3 bench_viewer.py &
sleep 1
curl -s http://localhost:8080 | grep "ttft-section"
kill %1
```

Expected: `<section id="ttft-section">` found in HTML output.

- [ ] **Step 6: Final commit**

```bash
git add bench_viewer.py
git commit -m "feat(viewer): add TTFT latency chart, task column in savings table"
```

---

## Summary of Changes

After all 11 tasks:

- **Bug fixed:** RTK A/B runs now share a single Claude plan — comparisons are clean
- **Bug fixed:** Tracker reset works because all callers use `get_tracker()` at call time
- **New metrics:** TTFT, generation time, per-tool context bytes, trim events, retry/reviewer counts — all recorded in JSONL and shown in viewer
- **New tasks:** `csv_pipeline`, `multifile_refactor`, `bug_hunt`, `git_audit` replace trivial fibonacci
- **New charts:** Per-tool stacked bar, trim events, TTFT latency, per-task savings table

Run a full benchmark after implementation:

```bash
python3 benchmark.py --no-rtk   # chat prompts only, quick sanity check
python3 benchmark.py            # full run with all 4 pipeline tasks (~20 min)
python3 bench_viewer.py         # open http://localhost:8080 to see results
```
