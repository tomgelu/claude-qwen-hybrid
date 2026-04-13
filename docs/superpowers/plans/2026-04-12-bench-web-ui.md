# Bench Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Bench Runs (A/B/C Quality)" section to bench_viewer.py that displays results written by bench.py into benchmark_results.jsonl.

**Architecture:** bench.py appends one JSON record per run to benchmark_results.jsonl using model_type="bench_run". The existing /data endpoint in bench_viewer.py serves the file unchanged. A new renderBenchRuns() JS function groups records by run_id and renders a comparison table plus two Chart.js bar charts.

**Tech Stack:** Python stdlib (json, time, datetime, pathlib), vanilla JS + Chart.js 4.4 (already loaded in viewer), existing dark-theme CSS classes.

---

### Task 1: Add wall_time_s to run_once()

**Files:**
- Modify: `bench.py`
- Test: `tests/test_bench_persist.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_bench_persist.py`:

```python
"""TDD tests for bench.py persistence — _write_bench_results and wall_time_s."""
import json
import os
import tempfile
import pytest


def test_run_once_result_includes_wall_time_s():
    """run_once() result dict must contain wall_time_s as a non-negative number."""
    from bench import run_once
    # We can't run the full pipeline in a unit test, so we test the key exists
    # on a stats dict produced by _make_empty_stats (a helper we add in Task 2).
    # For now just verify the key is documented in _average_stats keys.
    from bench import _average_stats
    import inspect
    src = inspect.getsource(_average_stats)
    assert "wall_time_s" in src, "_average_stats must include wall_time_s in its keys list"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/lgktg/claude-autonaumous
python3 -m pytest tests/test_bench_persist.py::test_run_once_result_includes_wall_time_s -v
```

Expected: FAIL — "wall_time_s not in src"

- [ ] **Step 3: Add wall_time_s to run_once() and _average_stats()**

In `bench.py`, add `import time` at the top alongside existing imports.

In `run_once()`, record start time before thread launch and compute elapsed after join:

```python
def run_once(label: str, use_rtk: bool, workspace: str, plan: dict,
             enable_phases: bool = False) -> dict:
    """Run the full pipeline in workspace using a pre-supplied plan. Returns token + quality stats."""
    os.environ["USE_RTK"]        = "true" if use_rtk else "false"
    os.environ["ENABLE_PHASES"]  = "true" if enable_phases else "false"
    os.environ["WORKSPACE_DIR"]  = workspace
    os.environ["STREAM_OUTPUT"]  = "false"

    _fresh_modules()

    import utils.token_tracker as tt_mod
    tt_mod.reset_tracker()

    from core.orchestrator import Orchestrator
    from utils.token_tracker import get_tracker
    orch = Orchestrator()

    print(f"\n{'='*60}")
    phases_tag = "  PHASES=on" if enable_phases else ""
    print(f"  RUN {label}  |  USE_RTK={use_rtk}{phases_tag}  |  workspace={workspace}")
    print(f"{'='*60}", flush=True)

    RUN_TIMEOUT = 480
    exc_holder   = []
    state_holder = []

    def _run():
        try:
            state = orch.run("", plan=plan)
            state_holder.append(state)
        except Exception as e:
            exc_holder.append(e)

    t_start = time.time()                          # ← ADD THIS
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=RUN_TIMEOUT)
    wall_time_s = int(time.time() - t_start)       # ← ADD THIS

    if t.is_alive():
        print(f"\n  [bench] RUN {label} timed out after {RUN_TIMEOUT}s — partial results only",
              flush=True)
    if exc_holder:
        print(f"\n  [bench] RUN {label} error: {exc_holder[0]}", flush=True)

    state   = state_holder[0] if state_holder else {"completed_steps": [], "failed_steps": [], "skipped_steps": []}
    quality = capture_quality(workspace, state)

    tr = get_tracker()
    return {
        "label":        label,
        "use_rtk":      use_rtk,
        "phases_enabled": enable_phases,           # ← ADD THIS
        "qwen_in":      tr._qwen_input,
        "qwen_out":     tr._qwen_output,
        "tool_bytes":   tr.tool_response_bytes,
        "claude_in":    tr._claude_input,
        "claude_out":   tr._claude_output,
        "wall_time_s":  wall_time_s,               # ← ADD THIS
        **quality,
    }
```

In `_average_stats()`, add `"wall_time_s"` to the keys list:

```python
def _average_stats(stats_list: list[dict]) -> dict:
    """Average numeric fields across multiple runs."""
    if not stats_list:
        return {}
    keys = ["qwen_in", "qwen_out", "tool_bytes", "claude_in", "claude_out",
            "steps_completed", "steps_failed", "steps_total",
            "tests_passed", "tests_failed", "wall_time_s"]
    avg = {**stats_list[0]}
    for key in keys:
        avg[key] = int(sum(s[key] for s in stats_list) / len(stats_list))
    return avg
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_bench_persist.py::test_run_once_result_includes_wall_time_s -v
```

Expected: PASS

---

### Task 2: Add _write_bench_results()

**Files:**
- Modify: `bench.py`
- Test: `tests/test_bench_persist.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bench_persist.py`:

```python
def test_write_bench_results_creates_file_with_correct_schema():
    """_write_bench_results appends one JSON line per stats dict to the given file."""
    from bench import _write_bench_results

    stats_list = [
        {
            "label": "A (no RTK)", "use_rtk": False, "phases_enabled": False,
            "qwen_in": 1000, "qwen_out": 100, "tool_bytes": 500,
            "claude_in": 0, "claude_out": 0, "wall_time_s": 42,
            "steps_completed": 3, "steps_failed": 0, "steps_total": 3,
            "tests_passed": 6, "tests_failed": 0,
        },
        {
            "label": "B (RTK)", "use_rtk": True, "phases_enabled": False,
            "qwen_in": 800, "qwen_out": 90, "tool_bytes": 300,
            "claude_in": 0, "claude_out": 0, "wall_time_s": 38,
            "steps_completed": 3, "steps_failed": 0, "steps_total": 3,
            "tests_passed": 6, "tests_failed": 0,
        },
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        out_path = f.name

    try:
        _write_bench_results("20260412_184301", "Build something", stats_list, out_path)

        lines = open(out_path).read().splitlines()
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"

        rec_a = json.loads(lines[0])
        assert rec_a["model_type"] == "bench_run"
        assert rec_a["run_id"] == "20260412_184301"
        assert rec_a["task"] == "Build something"
        assert rec_a["label"] == "A (no RTK)"
        assert rec_a["use_rtk"] is False
        assert rec_a["phases_enabled"] is False
        assert rec_a["qwen_in"] == 1000
        assert rec_a["tests_passed"] == 6
        assert rec_a["wall_time_s"] == 42

        rec_b = json.loads(lines[1])
        assert rec_b["label"] == "B (RTK)"
        assert rec_b["use_rtk"] is True
    finally:
        os.unlink(out_path)


def test_write_bench_results_appends_to_existing_file():
    """_write_bench_results appends — does not overwrite existing content."""
    from bench import _write_bench_results

    existing = {"existing": True}
    stats = [{
        "label": "A", "use_rtk": False, "phases_enabled": False,
        "qwen_in": 0, "qwen_out": 0, "tool_bytes": 0,
        "claude_in": 0, "claude_out": 0, "wall_time_s": 1,
        "steps_completed": 0, "steps_failed": 0, "steps_total": 0,
        "tests_passed": 0, "tests_failed": 0,
    }]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(existing) + "\n")
        out_path = f.name

    try:
        _write_bench_results("run2", "task", stats, out_path)
        lines = open(out_path).read().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == existing   # original line preserved
        assert json.loads(lines[1])["run_id"] == "run2"
    finally:
        os.unlink(out_path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_bench_persist.py::test_write_bench_results_creates_file_with_correct_schema tests/test_bench_persist.py::test_write_bench_results_appends_to_existing_file -v
```

Expected: FAIL — ImportError: cannot import name '_write_bench_results'

- [ ] **Step 3: Implement _write_bench_results()**

Add this function to `bench.py` immediately after `capture_quality()` and before `_fresh_modules()`. Also add `import json` and `from datetime import datetime` to the imports at the top (check if `json` is already imported — if so skip it).

```python
_RESULTS_FILE = Path(__file__).parent / "benchmark_results.jsonl"


def _write_bench_results(
    run_id: str,
    task: str,
    stats_list: list[dict],
    out_path=None,
) -> None:
    """
    Append one JSON record per run to benchmark_results.jsonl.

    Each record carries model_type="bench_run" so bench_viewer.py can
    filter it from chat/pipeline rows.

    out_path: override the default file path (used in tests).
    """
    path = Path(out_path) if out_path else _RESULTS_FILE
    with open(path, "a") as f:
        for stats in stats_list:
            record = {
                "run_id":          run_id,
                "model_type":      "bench_run",
                "task":            task,
                "label":           stats.get("label", ""),
                "use_rtk":         stats.get("use_rtk", False),
                "phases_enabled":  stats.get("phases_enabled", False),
                "qwen_in":         stats.get("qwen_in", 0),
                "qwen_out":        stats.get("qwen_out", 0),
                "tool_bytes":      stats.get("tool_bytes", 0),
                "claude_in":       stats.get("claude_in", 0),
                "claude_out":      stats.get("claude_out", 0),
                "steps_completed": stats.get("steps_completed", 0),
                "steps_failed":    stats.get("steps_failed", 0),
                "steps_total":     stats.get("steps_total", 0),
                "tests_passed":    stats.get("tests_passed", 0),
                "tests_failed":    stats.get("tests_failed", 0),
                "wall_time_s":     stats.get("wall_time_s", 0),
            }
            f.write(json.dumps(record) + "\n")
```

Also add to the imports at the top of `bench.py`:

```python
import json
import time
from datetime import datetime
from pathlib import Path
```

(Remove any duplicates if `json` is already there.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_bench_persist.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add bench.py tests/test_bench_persist.py
git commit -m "feat(bench): add wall_time_s and _write_bench_results for web UI persistence"
```

---

### Task 3: Wire _write_bench_results into main()

**Files:**
- Modify: `bench.py`

- [ ] **Step 1: Update main() to call _write_bench_results**

In `main()`, after the line `print(format_results_table(runs, task))`, add:

```python
    # Persist results to benchmark_results.jsonl for bench_viewer.py
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    _write_bench_results(run_id, task, all_a + all_b + all_c)
    print(f"\n  Results saved → benchmark_results.jsonl  (run_id={run_id})")
```

- [ ] **Step 2: Verify all existing tests still pass**

```bash
python3 -m pytest tests/test_bench_quality.py tests/test_bench_table.py tests/test_bench_persist.py -v
```

Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add bench.py
git commit -m "feat(bench): persist A/B/C results to benchmark_results.jsonl after each run"
```

---

### Task 4: Add Bench Runs section to bench_viewer.py

**Files:**
- Modify: `bench_viewer.py`

- [ ] **Step 1: Add the HTML section**

In `bench_viewer.py`, locate the `<section id="rtk-section">` block. Add the new section immediately **after** it (before the Chat Prompts section):

```html
  <section id="bench-section">
    <h2>Bench Runs (A/B/C Quality)</h2>
    <div class="cards" id="bench-cards"></div>
    <div class="charts" id="bench-charts"></div>
    <div style="margin-top:1.2rem">
      <table id="bench-table">
        <thead><tr>
          <th>Metric</th>
          <th id="bench-col-a">A</th>
          <th id="bench-col-b">B</th>
          <th id="bench-col-c" style="display:none">C</th>
        </tr></thead>
        <tbody id="bench-body"></tbody>
      </table>
    </div>
    <div style="margin-top:1.5rem">
      <h2 style="font-size:.9rem;color:#6b7280;margin-bottom:.6rem">Run History</h2>
      <table>
        <thead><tr>
          <th>Run ID</th><th>Task</th><th>A tests</th><th>B tests</th><th>C tests</th><th>RTK saving</th>
        </tr></thead>
        <tbody id="bench-history"></tbody>
      </table>
    </div>
  </section>
```

- [ ] **Step 2: Add renderBenchRuns() JS function**

In the `<script>` block, add this function after `renderChat()`:

```javascript
function renderBenchRuns(rows) {
  // Group rows by run_id — each group is one A/B or A/B/C comparison set
  const groups = {};
  for (const r of rows) {
    if (!groups[r.run_id]) groups[r.run_id] = [];
    groups[r.run_id].push(r);
  }
  const sortedIds = Object.keys(groups).sort().reverse();

  if (!sortedIds.length) {
    document.getElementById('bench-cards').innerHTML =
      '<p class="empty">No bench runs yet — run: python3 bench.py --phases "your task"</p>';
    return;
  }

  // Summary cards from most recent group
  const latest = groups[sortedIds[0]];
  const a = latest.find(r => r.label.startsWith('A')) || {};
  const b = latest.find(r => r.label.startsWith('B')) || {};
  const c = latest.find(r => r.label.startsWith('C'));

  const rtkSaving = a.qwen_in && b.qwen_in
    ? Math.round((a.qwen_in - b.qwen_in) / a.qwen_in * 100) + '%'
    : '—';
  const bestTests = Math.max(a.tests_passed || 0, b.tests_passed || 0, c ? (c.tests_passed || 0) : 0);
  const totalTests = Math.max(a.steps_total || 0, b.steps_total || 0, c ? (c.steps_total || 0) : 0);
  const phasesCost = c ? fmt(c.claude_in) + ' tokens' : '—';

  document.getElementById('bench-cards').innerHTML = [
    { val: sortedIds.length,        lbl: 'Bench run sets' },
    { val: rtkSaving,               lbl: 'RTK token saving (latest)' },
    { val: bestTests + '/' + (a.tests_passed != null ? (a.tests_passed + a.tests_failed) : '?'), lbl: 'Best test score' },
    { val: phasesCost,              lbl: 'Phases Claude cost' },
  ].map(c => `<div class="card"><div class="val">${c.val}</div><div class="lbl">${c.lbl}</div></div>`).join('');

  // Show/hide C column
  const hasC = !!c;
  document.getElementById('bench-col-c').style.display = hasC ? '' : 'none';
  if (a.label) document.getElementById('bench-col-a').textContent = a.label;
  if (b.label) document.getElementById('bench-col-b').textContent = b.label;
  if (c)       document.getElementById('bench-col-c').textContent = c.label;

  // Comparison table for most recent group
  function qCell(val, base) {
    const num = fmt(val);
    if (!base || val === base) return num;
    const d = val - base, pct = d / base * 100;
    const cls = d < 0 ? 'delta-pos' : 'delta-neg';
    return `${num} <span class="${cls}">${d < 0 ? '▼' : '▲'}${Math.abs(pct).toFixed(1)}%</span>`;
  }

  // Quality cells: higher is better for tests_passed/steps_completed, lower for failures
  function qQual(val, base, higherIsBetter) {
    const num = fmt(val);
    if (!base || val === base) return num;
    const d = val - base;
    const improved = higherIsBetter ? d > 0 : d < 0;
    const cls = improved ? 'delta-pos' : 'delta-neg';
    return `${num} <span class="${cls}">${d > 0 ? '▲' : '▼'}${Math.abs(d)}</span>`;
  }

  const ROWS = [
    // [section header, null] or [label, key, type]  type: 'token'|'qual-high'|'qual-low'|'info'
    ['Token Efficiency', null],
    ['Qwen input tokens',    'qwen_in',         'token'],
    ['Qwen output tokens',   'qwen_out',        'token'],
    ['Tool resp bytes',      'tool_bytes',      'token'],
    ['Claude input tokens',  'claude_in',       'token'],
    ['Claude output tokens', 'claude_out',      'token'],
    ['Output Quality', null],
    ['Steps completed',      'steps_completed', 'qual-high'],
    ['Tests passed',         'tests_passed',    'qual-high'],
    ['Tests failed',         'tests_failed',    'qual-low'],
    ['Run Info', null],
    ['Wall time (s)',         'wall_time_s',     'token'],
  ];

  const tbody = document.getElementById('bench-body');
  tbody.innerHTML = '';
  for (const row of ROWS) {
    const [label, key, type] = row;
    if (!key) {
      // Section header row
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="4" style="background:#12121a;color:#6b7280;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;padding:.3rem .7rem">${label}</td>`;
      tbody.appendChild(tr);
      continue;
    }
    const tr = document.createElement('tr');
    const aVal = a[key] ?? 0, bVal = b[key] ?? 0, cVal = c ? (c[key] ?? 0) : null;
    let bCell, cCell;
    if (type === 'token') {
      bCell = qCell(bVal, aVal);
      cCell = cVal != null ? qCell(cVal, aVal) : '—';
    } else if (type === 'qual-high') {
      bCell = qQual(bVal, aVal, true);
      cCell = cVal != null ? qQual(cVal, aVal, true) : '—';
    } else {
      bCell = qQual(bVal, aVal, false);
      cCell = cVal != null ? qQual(cVal, aVal, false) : '—';
    }
    tr.innerHTML = `
      <td style="padding:.4rem .7rem">${label}</td>
      <td style="text-align:right;padding:.4rem .7rem;font-family:monospace">${fmt(aVal)}</td>
      <td style="text-align:right;padding:.4rem .7rem;font-family:monospace">${bCell}</td>
      <td style="text-align:right;padding:.4rem .7rem;font-family:monospace;display:${hasC ? '' : 'none'}">${cCell}</td>`;
    tbody.appendChild(tr);
  }

  // Charts
  charts.forEach(c => c.destroy()); charts = [];
  const chartsDiv = document.getElementById('bench-charts');
  chartsDiv.innerHTML = '';

  const chartDefs = [
    { key: 'qwen_in',      label: 'Qwen Input Tokens',  color: ['rgba(248,113,113,.7)', 'rgba(134,239,172,.7)', 'rgba(167,139,250,.7)'] },
    { key: 'tests_passed', label: 'Tests Passed',        color: ['rgba(248,113,113,.7)', 'rgba(134,239,172,.7)', 'rgba(167,139,250,.7)'] },
  ];

  for (const def of chartDefs) {
    const wrap = document.createElement('div');
    wrap.className = 'chart-wrap';
    wrap.innerHTML = `<h3>${def.label}</h3><canvas></canvas>`;
    chartsDiv.appendChild(wrap);
    const labels = sortedIds.map(id => id.replace(/^(\d{4})(\d{2})(\d{2})_/, '$1-$2-$3 '));
    const datasets = ['A', 'B', 'C'].map((letter, i) => ({
      label: letter,
      data: sortedIds.map(id => {
        const run = groups[id].find(r => r.label.startsWith(letter));
        return run ? (run[def.key] || 0) : 0;
      }),
      backgroundColor: def.color[i],
      borderRadius: 4,
    })).filter((_, i) => i < 2 || hasC);
    charts.push(new Chart(wrap.querySelector('canvas'), {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true,
        plugins: { legend: { labels: { color: '#9ca3af', font: { size: 11 } } } },
        scales: {
          x: { ticks: { color: '#6b7280', font: { size: 10 } }, grid: { color: '#1e1e2e' } },
          y: { ticks: { color: '#6b7280', font: { size: 10 } }, grid: { color: '#1e1e2e' } },
        }
      }
    }));
  }

  // History table
  const histBody = document.getElementById('bench-history');
  histBody.innerHTML = '';
  for (const rid of sortedIds) {
    const grp = groups[rid];
    const ra = grp.find(r => r.label.startsWith('A')) || {};
    const rb = grp.find(r => r.label.startsWith('B')) || {};
    const rc = grp.find(r => r.label.startsWith('C'));
    const saving = ra.qwen_in && rb.qwen_in
      ? '<span class="delta-pos">▼' + Math.round((ra.qwen_in - rb.qwen_in) / ra.qwen_in * 100) + '%</span>'
      : '—';
    const taskSnip = (ra.task || rb.task || '').slice(0, 50) + '…';
    const testCell = (t) => t == null ? '—'
      : t.tests_failed === 0
        ? `<span class="delta-pos">${t.tests_passed}/${t.tests_passed + t.tests_failed} ✓</span>`
        : `<span class="delta-neg">${t.tests_passed}/${t.tests_passed + t.tests_failed} ✗</span>`;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="run-label">${rid}</td>
      <td style="font-size:.75rem;color:#9ca3af">${taskSnip}</td>
      <td>${testCell(ra)}</td>
      <td>${testCell(rb)}</td>
      <td>${testCell(rc)}</td>
      <td>${saving}</td>`;
    histBody.appendChild(tr);
  }
}
```

- [ ] **Step 3: Wire renderBenchRuns into render()**

In the `render(rows)` function, add a call to `renderBenchRuns` after `renderChat`:

```javascript
function render(rows) {
  const pipeline  = rows.filter(r => r.model_type === 'pipeline' && !r.error);
  const chat      = rows.filter(r => r.model_type !== 'pipeline' && r.model_type !== 'bench_run');
  const benchRuns = rows.filter(r => r.model_type === 'bench_run');   // ← ADD

  // Cards — update RTK pairs count to exclude bench_run rows
  const runs   = [...new Set(rows.map(r => r.run_id))];
  const models = [...new Set(rows.map(r => r.model))];
  document.getElementById('cards').innerHTML = [
    { val: runs.length,                          lbl: 'Total runs' },
    { val: models.length,                        lbl: 'Models' },
    { val: pipeline.length / 2 | 0,             lbl: 'RTK pairs' },
    { val: chat.filter(r => !r.error).length,    lbl: 'Chat samples' },
  ].map(c => `<div class="card"><div class="val">${c.val}</div><div class="lbl">${c.lbl}</div></div>`).join('');

  renderRtk(pipeline);
  renderBenchRuns(benchRuns);   // ← ADD
  renderChat(chat);
}
```

- [ ] **Step 4: Smoke-test the viewer manually**

```bash
cd /home/lgktg/claude-autonaumous
python3 bench_viewer.py &
```

Open http://localhost:8080 in a browser. Verify:
- "Bench Runs (A/B/C Quality)" section appears
- Shows "No bench runs yet — run: python3 bench.py..." message (since file may be empty)
- No JS errors in browser console
- Existing RTK Pipeline and Chat sections still render correctly

- [ ] **Step 5: Run a minimal bench.py to generate a record and verify it shows in the UI**

```bash
python3 bench.py "Write a Python function add(a, b) that returns a + b. Add a test in test_add.py. Run tests."
```

After it completes:
- Verify `benchmark_results.jsonl` contains lines with `"model_type": "bench_run"`
- Refresh http://localhost:8080
- Verify Bench Runs section now shows the comparison table with A/B rows
- Verify summary cards show RTK saving %
- Verify history table shows one row

- [ ] **Step 6: Commit**

```bash
git add bench_viewer.py
git commit -m "feat(bench-viewer): add Bench Runs section with A/B/C table and quality charts"
```

---

### Task 5: Final integration test

**Files:**
- Run: `tests/test_bench_persist.py`

- [ ] **Step 1: Run all bench tests**

```bash
cd /home/lgktg/claude-autonaumous
python3 -m pytest tests/test_bench_quality.py tests/test_bench_table.py tests/test_bench_persist.py -v
```

Expected output:
```
tests/test_bench_quality.py::test_capture_quality_counts_completed_steps PASSED
tests/test_bench_quality.py::test_capture_quality_counts_failed_steps PASSED
tests/test_bench_quality.py::test_capture_quality_computes_total_from_completed_and_failed PASSED
tests/test_bench_quality.py::test_capture_quality_runs_pytest_and_reports_passing_tests PASSED
tests/test_bench_quality.py::test_capture_quality_reports_failing_tests PASSED
tests/test_bench_quality.py::test_capture_quality_returns_zero_tests_when_no_test_files PASSED
tests/test_bench_table.py::test_two_runs_produce_two_data_columns PASSED
tests/test_bench_table.py::test_three_runs_produce_three_data_columns PASSED
tests/test_bench_table.py::test_table_contains_token_metrics PASSED
tests/test_bench_table.py::test_table_contains_quality_metrics PASSED
tests/test_bench_table.py::test_table_shows_claude_tokens_for_phases_run PASSED
tests/test_bench_table.py::test_table_shows_decrease_indicator_when_second_run_is_lower PASSED
tests/test_bench_table.py::test_table_shows_increase_indicator_when_second_run_is_higher PASSED
tests/test_bench_table.py::test_table_task_name_is_truncated_to_fit PASSED
tests/test_bench_persist.py::test_run_once_result_includes_wall_time_s PASSED
tests/test_bench_persist.py::test_write_bench_results_creates_file_with_correct_schema PASSED
tests/test_bench_persist.py::test_write_bench_results_appends_to_existing_file PASSED

17 passed
```

- [ ] **Step 2: Final commit**

```bash
git add .
git commit -m "test(bench): all 17 bench tests passing — quality, table, persistence"
```
