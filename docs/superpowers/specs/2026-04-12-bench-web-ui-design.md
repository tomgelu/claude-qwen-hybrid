# Bench Runs Web UI Design

**Date:** 2026-04-12  
**Status:** Approved

---

## Overview

Add a "Bench Runs (A/B/C Quality)" section to the existing `bench_viewer.py` dashboard. `bench.py` writes one JSON record per run to `benchmark_results.jsonl`. The viewer's frontend filters by `model_type: "bench_run"` and renders a grouped comparison table plus two Chart.js bar charts.

No new server, no new file, no schema migration — the existing `/data` endpoint serves everything already.

---

## Data Flow

```
bench.py
  └─ main() → run A, run B, [run C] → _write_bench_results(run_id, task, stats_list)
        └─ appends one JSON line per run to benchmark_results.jsonl

bench_viewer.py
  └─ /data endpoint → reads benchmark_results.jsonl → returns all rows as JSON
        └─ frontend: filters model_type === "bench_run" → renderBenchRuns(rows)
```

---

## JSON Record Schema

One record per run (A, B, or C). `run_id` groups an A/B or A/B/C set together.

```json
{
  "run_id":          "20260412_184301",
  "model_type":      "bench_run",
  "task":            "Build a Flask REST API...",
  "label":           "A (no RTK)",
  "use_rtk":         false,
  "phases_enabled":  false,
  "qwen_in":         276790,
  "qwen_out":        7438,
  "tool_bytes":      56659,
  "claude_in":       0,
  "claude_out":      0,
  "steps_completed": 3,
  "steps_failed":    0,
  "steps_total":     3,
  "tests_passed":    6,
  "tests_failed":    0,
  "wall_time_s":     312
}
```

`wall_time_s` is measured from the start of `run_once()` to its return (includes timeout).

---

## bench.py Changes

### `_write_bench_results(run_id, task, stats_list)`

New function added near the top of `bench.py` (after `capture_quality`).

- `run_id`: `datetime.now().strftime("%Y%m%d_%H%M%S")`
- `task`: the task string passed to `main()`
- `stats_list`: list of raw stats dicts from `run_once()` (one per A/B/C run)

Appends one line per stats dict to `benchmark_results.jsonl` in the repo root. Creates the file if it does not exist.

### `run_once()` change

Measure wall time: record `time.time()` before and after the thread join. Add `wall_time_s` to the returned dict.

### `main()` change

At the end, after printing the table, call `_write_bench_results(run_id, task, all_a + all_b + all_c)`.

---

## bench_viewer.py Changes

### New section in HTML

Add below the RTK Pipeline section, above Chat Prompts:

```html
<section id="bench-section">
  <h2>Bench Runs (A/B/C Quality)</h2>
  <div id="bench-cards" class="cards"></div>
  <div class="charts" id="bench-charts"></div>
  <div style="margin-top:1.2rem">
    <table id="bench-table">...</table>
  </div>
</section>
```

### `renderBenchRuns(rows)` function

Groups rows by `run_id`. For each group:

**Summary cards (most recent group only):**
- RTK token savings % (A→B qwen_in delta)
- Tests passed — best run
- Phases Claude token cost (C claude_in, or "—" if no C run)
- Wall time range

**Comparison table columns:** one per label (A / B / C).  
**Row groups:**

| Group | Rows |
|---|---|
| Token Efficiency | Qwen input, Qwen output, Tool bytes, Claude input, Claude output |
| Output Quality | Steps completed/total, Tests passed/total, Tests failed |
| Run Info | Task (truncated), Wall time, RTK, Phases |

Change indicators (▼/▲ + %) shown in B and C columns vs A baseline. Colour: green = improvement (lower tokens OR higher quality), red = regression.

**Two Chart.js bar charts:**
- Qwen Input Tokens — one bar group per `run_id`, A/B/C bars per group
- Tests Passed — same structure

Both charts reuse the existing dark-theme Chart.js config already in the viewer.

### History table

Below the charts, a collapsible history table showing all bench run groups (newest first): `run_id`, task snippet, A tests, B tests, C tests, RTK savings %.

---

## Files Changed

| File | Change |
|---|---|
| `bench.py` | Add `_write_bench_results()`, add `wall_time_s` to `run_once()`, call writer in `main()` |
| `bench_viewer.py` | Add Bench Runs section to HTML, add `renderBenchRuns()` JS function, wire into `render()` |

**No other files modified.**

---

## Out of Scope

- Auto-refresh / polling (existing manual Refresh button is sufficient)
- Editing or deleting past bench runs from the UI
- Per-step breakdown within a run
- Exporting results to CSV
