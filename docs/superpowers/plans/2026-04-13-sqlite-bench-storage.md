# SQLite Bench Storage + Run Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `benchmark_results.jsonl` with a SQLite database and add a side-by-side run comparison panel to the viewer.

**Architecture:** `bench.py` writes rows to `benchmark_results.db` via `sqlite3`; `bench_viewer.py` reads the same DB via its `/data` endpoint and returns the same JSON shape the existing JS already expects. The comparison panel is pure JS — no new HTTP endpoints.

**Tech Stack:** Python stdlib (`sqlite3`, `json`, `pathlib`), vanilla JS, existing dark CSS theme.

---

### Task 1: Update .gitignore and delete stale files

**Files:**
- Modify: `.gitignore`
- Delete: `benchmark_results.jsonl` (if present)
- Delete: `.superpowers/brainstorm/` (scratch from failed visual companion session)

- [ ] **Step 1: Add missing entries to .gitignore**

Open `.gitignore` and add these lines at the bottom:

```
# SQLite databases
benchmark_results.db
tasks.db

# Superpowers brainstorm scratch
.superpowers/
```

- [ ] **Step 2: Delete stale files**

```bash
cd /home/lgktg/claude-autonaumous
rm -f benchmark_results.jsonl
rm -rf .superpowers/brainstorm
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: update .gitignore — add *.db and .superpowers/, remove stale JSONL"
```

---

### Task 2: Rewrite persistence tests for SQLite

**Files:**
- Modify: `tests/test_bench_persist.py`

The existing tests use temp `.jsonl` files. Rewrite the two schema/append tests to use a temp `.db` path and query via `sqlite3`. The `wall_time_s` test is unchanged.

- [ ] **Step 1: Replace the two failing tests**

Replace the full contents of `tests/test_bench_persist.py` with:

```python
"""TDD tests for bench.py persistence — _write_bench_results and wall_time_s."""
import os
import sqlite3
import tempfile
import pytest


def test_run_once_result_includes_wall_time_s():
    """_average_stats must include wall_time_s — documents run_once() contract."""
    from bench import _average_stats
    import inspect
    src = inspect.getsource(_average_stats)
    assert "wall_time_s" in src, "_average_stats must include wall_time_s in its keys list"


def test_write_bench_results_creates_db_with_correct_schema():
    """_write_bench_results inserts one row per stats dict into a SQLite DB."""
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

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)   # let _write_bench_results create it fresh

    try:
        _write_bench_results("20260412_184301", "Build something", stats_list, db_path)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM bench_runs ORDER BY id").fetchall()
        conn.close()

        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"

        rec_a = dict(rows[0])
        assert rec_a["run_id"] == "20260412_184301"
        assert rec_a["task"] == "Build something"
        assert rec_a["label"] == "A (no RTK)"
        assert rec_a["use_rtk"] == 0        # stored as int
        assert rec_a["phases_enabled"] == 0
        assert rec_a["qwen_in"] == 1000
        assert rec_a["tests_passed"] == 6
        assert rec_a["wall_time_s"] == 42

        rec_b = dict(rows[1])
        assert rec_b["label"] == "B (RTK)"
        assert rec_b["use_rtk"] == 1
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_write_bench_results_accumulates_across_calls():
    """Calling _write_bench_results twice appends rows — does not overwrite."""
    from bench import _write_bench_results

    stats = [{
        "label": "A", "use_rtk": False, "phases_enabled": False,
        "qwen_in": 0, "qwen_out": 0, "tool_bytes": 0,
        "claude_in": 0, "claude_out": 0, "wall_time_s": 1,
        "steps_completed": 0, "steps_failed": 0, "steps_total": 0,
        "tests_passed": 0, "tests_failed": 0,
    }]

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)

    try:
        _write_bench_results("run1", "task one", stats, db_path)
        _write_bench_results("run2", "task two", stats, db_path)

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT run_id FROM bench_runs ORDER BY id").fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0][0] == "run1"
        assert rows[1][0] == "run2"
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/lgktg/claude-autonaumous
python3 -m pytest tests/test_bench_persist.py -v 2>&1 | tail -20
```

Expected: `test_write_bench_results_creates_db_with_correct_schema` FAILS with something like `OperationalError: no such table: bench_runs` or `AssertionError` because the old implementation still writes JSONL.

---

### Task 3: Implement SQLite storage in bench.py

**Files:**
- Modify: `bench.py`

Replace the JSONL write logic with SQLite. Keep the function signature identical.

- [ ] **Step 1: Replace `_RESULTS_FILE` and `_write_bench_results` in bench.py**

Find this block in `bench.py` (around line 84):

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

Replace it with:

```python
_DB_FILE   = Path(__file__).parent / "benchmark_results.db"
_JSONL_FILE = Path(__file__).parent / "benchmark_results.jsonl"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS bench_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    task            TEXT    NOT NULL DEFAULT '',
    label           TEXT    NOT NULL DEFAULT '',
    use_rtk         INTEGER NOT NULL DEFAULT 0,
    phases_enabled  INTEGER NOT NULL DEFAULT 0,
    qwen_in         INTEGER NOT NULL DEFAULT 0,
    qwen_out        INTEGER NOT NULL DEFAULT 0,
    tool_bytes      INTEGER NOT NULL DEFAULT 0,
    claude_in       INTEGER NOT NULL DEFAULT 0,
    claude_out      INTEGER NOT NULL DEFAULT 0,
    steps_completed INTEGER NOT NULL DEFAULT 0,
    steps_failed    INTEGER NOT NULL DEFAULT 0,
    steps_total     INTEGER NOT NULL DEFAULT 0,
    tests_passed    INTEGER NOT NULL DEFAULT 0,
    tests_failed    INTEGER NOT NULL DEFAULT 0,
    wall_time_s     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

_INSERT_ROW = """
INSERT INTO bench_runs
    (run_id, task, label, use_rtk, phases_enabled,
     qwen_in, qwen_out, tool_bytes, claude_in, claude_out,
     steps_completed, steps_failed, steps_total,
     tests_passed, tests_failed, wall_time_s)
VALUES
    (:run_id, :task, :label, :use_rtk, :phases_enabled,
     :qwen_in, :qwen_out, :tool_bytes, :claude_in, :claude_out,
     :steps_completed, :steps_failed, :steps_total,
     :tests_passed, :tests_failed, :wall_time_s)
"""


def _write_bench_results(
    run_id: str,
    task: str,
    stats_list: list[dict],
    out_path=None,
) -> None:
    """
    Insert one row per run into benchmark_results.db.

    out_path: override the default DB path (used in tests — pass a temp .db path).
    If benchmark_results.jsonl exists alongside the DB, its records are migrated
    into the DB and the file is deleted.
    """
    import sqlite3 as _sqlite3
    db_path = Path(out_path) if out_path else _DB_FILE
    conn = _sqlite3.connect(str(db_path))
    conn.execute(_CREATE_TABLE)

    # One-time JSONL migration (only runs when using the real DB, not test overrides)
    if out_path is None and _JSONL_FILE.exists():
        _migrate_jsonl(conn)

    for stats in stats_list:
        conn.execute(_INSERT_ROW, {
            "run_id":          run_id,
            "task":            task,
            "label":           stats.get("label", ""),
            "use_rtk":         int(bool(stats.get("use_rtk", False))),
            "phases_enabled":  int(bool(stats.get("phases_enabled", False))),
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
        })
    conn.commit()
    conn.close()


def _migrate_jsonl(conn) -> None:
    """Import records from benchmark_results.jsonl into the open DB connection, then delete the file."""
    migrated = 0
    for line in _JSONL_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("model_type") != "bench_run":
            continue
        conn.execute(_INSERT_ROW, {
            "run_id":          rec.get("run_id", ""),
            "task":            rec.get("task", ""),
            "label":           rec.get("label", ""),
            "use_rtk":         int(bool(rec.get("use_rtk", False))),
            "phases_enabled":  int(bool(rec.get("phases_enabled", False))),
            "qwen_in":         rec.get("qwen_in", 0),
            "qwen_out":        rec.get("qwen_out", 0),
            "tool_bytes":      rec.get("tool_bytes", 0),
            "claude_in":       rec.get("claude_in", 0),
            "claude_out":      rec.get("claude_out", 0),
            "steps_completed": rec.get("steps_completed", 0),
            "steps_failed":    rec.get("steps_failed", 0),
            "steps_total":     rec.get("steps_total", 0),
            "tests_passed":    rec.get("tests_passed", 0),
            "tests_failed":    rec.get("tests_failed", 0),
            "wall_time_s":     rec.get("wall_time_s", 0),
        })
        migrated += 1
    conn.commit()
    _JSONL_FILE.unlink()
    print(f"  [bench] Migrated {migrated} records from JSONL → SQLite", flush=True)
```

- [ ] **Step 2: Run all bench tests**

```bash
cd /home/lgktg/claude-autonaumous
python3 -m pytest tests/test_bench_persist.py tests/test_bench_quality.py tests/test_bench_table.py -v 2>&1 | tail -25
```

Expected: all 17 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add bench.py tests/test_bench_persist.py
git commit -m "feat(bench): replace JSONL persistence with SQLite — adds _write_bench_results SQLite impl and JSONL migration"
```

---

### Task 4: Update bench_viewer.py /data endpoint to read from SQLite

**Files:**
- Modify: `bench_viewer.py`

- [ ] **Step 1: Replace RESULTS_FILE constant and /data handler**

At the top of `bench_viewer.py`, find:

```python
RESULTS_FILE = Path(__file__).parent / "benchmark_results.jsonl"
```

Replace with:

```python
DB_FILE = Path(__file__).parent / "benchmark_results.db"
```

Then find the `/data` handler inside `do_GET`:

```python
        if self.path == "/data":
            rows = []
            if RESULTS_FILE.exists():
                for line in RESULTS_FILE.read_text().splitlines():
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
```

Replace with:

```python
        if self.path == "/data":
            rows = []
            if DB_FILE.exists():
                import sqlite3 as _sq
                conn = _sq.connect(str(DB_FILE))
                conn.row_factory = _sq.Row
                try:
                    for r in conn.execute("SELECT *, 'bench_run' AS model_type FROM bench_runs ORDER BY created_at"):
                        rows.append(dict(r))
                except _sq.OperationalError:
                    pass   # table doesn't exist yet
                finally:
                    conn.close()
```

- [ ] **Step 2: Smoke-test the viewer**

```bash
cd /home/lgktg/claude-autonaumous
python3 bench_viewer.py &
sleep 1
curl -s http://localhost:8080/data | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} rows')"
kill %1
```

Expected output: `0 rows` (or N rows if `benchmark_results.db` already exists).

- [ ] **Step 3: Commit**

```bash
git add bench_viewer.py
git commit -m "feat(bench-viewer): read bench runs from SQLite instead of JSONL"
```

---

### Task 5: Add run comparison UI to bench_viewer.py

**Files:**
- Modify: `bench_viewer.py`

This task makes three JS changes:
1. Promote `ROWS`, `qCell`, `qQual` from local scope inside `renderBenchRuns` to module scope so `runComparison()` can reuse them.
2. Add a `let benchGroups = {}` module-level variable.
3. Add checkbox column + Compare button + comparison panel HTML and wire everything up.

- [ ] **Step 1: Promote ROWS, qCell, qQual to module scope**

In the `<script>` block of `bench_viewer.py`, find the start of `function renderBenchRuns(rows) {` and locate these three definitions inside it:

```javascript
  function qCell(val, base) {
    const num = fmt(val);
    if (!base || val === base) return num;
    const d = val - base, pct = d / base * 100;
    const cls = d < 0 ? 'delta-pos' : 'delta-neg';
    return `${num} <span class="${cls}">${d < 0 ? '▼' : '▲'}${Math.abs(pct).toFixed(1)}%</span>`;
  }

  function qQual(val, base, higherIsBetter) {
    const num = fmt(val);
    if (!base || val === base) return num;
    const d = val - base;
    const improved = higherIsBetter ? d > 0 : d < 0;
    const cls = improved ? 'delta-pos' : 'delta-neg';
    return `${num} <span class="${cls}">${d > 0 ? '▲' : '▼'}${Math.abs(d)}</span>`;
  }

  const ROWS = [
    ['Token Efficiency', null, null],
    ['Qwen input tokens',    'qwen_in',         'token'],
    ['Qwen output tokens',   'qwen_out',        'token'],
    ['Tool resp bytes',      'tool_bytes',      'token'],
    ['Claude input tokens',  'claude_in',       'token'],
    ['Claude output tokens', 'claude_out',      'token'],
    ['Output Quality', null, null],
    ['Steps completed',      'steps_completed', 'qual-high'],
    ['Tests passed',         'tests_passed',    'qual-high'],
    ['Tests failed',         'tests_failed',    'qual-low'],
    ['Run Info', null, null],
    ['Wall time (s)',         'wall_time_s',     'token'],
  ];
```

Move all three (removing them from inside the function) to the top of the `<script>` block, right after `let charts = [];`. Change `const ROWS` to `const ROWS` (keep as const, it's at module scope now). Remove the `function` keyword from `qCell` and `qQual` and declare them as `function qCell(...)` at module scope. The result at the top of `<script>` should be:

```javascript
let charts = [];
let benchGroups = {};

function fmt(n) { return n == null ? '—' : Number(n).toLocaleString(); }
function fmtMs(s) { return s == null ? '—' : Math.round(s * 1000).toLocaleString() + ' ms'; }
function fmtCost(c) { return c ? '$' + Number(c).toFixed(4) : '—'; }
function delta(a, b) {
  if (a == null || b == null || a === 0) return '';
  const d = b - a, pct = d / a * 100;
  const cls = d < 0 ? 'delta-pos' : d > 0 ? 'delta-neg' : 'delta-neu';
  const sign = d < 0 ? '▼' : d > 0 ? '▲' : '';
  return `<span class="${cls}">${sign}${Math.abs(pct).toFixed(1)}%</span>`;
}

function qCell(val, base) {
  const num = fmt(val);
  if (!base || val === base) return num;
  const d = val - base, pct = d / base * 100;
  const cls = d < 0 ? 'delta-pos' : 'delta-neg';
  return `${num} <span class="${cls}">${d < 0 ? '▼' : '▲'}${Math.abs(pct).toFixed(1)}%</span>`;
}

function qQual(val, base, higherIsBetter) {
  const num = fmt(val);
  if (!base || val === base) return num;
  const d = val - base;
  const improved = higherIsBetter ? d > 0 : d < 0;
  const cls = improved ? 'delta-pos' : 'delta-neg';
  return `${num} <span class="${cls}">${d > 0 ? '▲' : '▼'}${Math.abs(d)}</span>`;
}

const ROWS = [
  ['Token Efficiency', null, null],
  ['Qwen input tokens',    'qwen_in',         'token'],
  ['Qwen output tokens',   'qwen_out',        'token'],
  ['Tool resp bytes',      'tool_bytes',      'token'],
  ['Claude input tokens',  'claude_in',       'token'],
  ['Claude output tokens', 'claude_out',      'token'],
  ['Output Quality', null, null],
  ['Steps completed',      'steps_completed', 'qual-high'],
  ['Tests passed',         'tests_passed',    'qual-high'],
  ['Tests failed',         'tests_failed',    'qual-low'],
  ['Run Info', null, null],
  ['Wall time (s)',         'wall_time_s',     'token'],
];
```

Then inside `renderBenchRuns`, remove the now-duplicate local definitions of `qCell`, `qQual`, and `ROWS` (they are now at module scope).

Also add `benchGroups = {};` at the very start of `renderBenchRuns`, and change the local `const groups = {};` / `groups[r.run_id]` loop to assign to `benchGroups` instead:

```javascript
function renderBenchRuns(rows) {
  benchGroups = {};
  for (const r of rows) {
    if (!benchGroups[r.run_id]) benchGroups[r.run_id] = [];
    benchGroups[r.run_id].push(r);
  }
  const sortedIds = Object.keys(benchGroups).sort().reverse();
  // ... rest of function uses benchGroups instead of groups
```

Update all remaining references inside `renderBenchRuns` from `groups` → `benchGroups`.

- [ ] **Step 2: Add comparison HTML to the bench section**

In the HTML, find the `<div style="margin-top:1.5rem">` block that wraps the Run History table inside `<section id="bench-section">`. Add the Compare button and panel immediately before it:

```html
    <div style="display:flex;align-items:center;gap:.75rem;margin:.75rem 0 .5rem">
      <button id="compare-btn" disabled onclick="runComparison()"
        style="background:#1e1e2e;border:1px solid #2e2e3e;color:#e2e2e8;padding:.35rem .9rem;border-radius:6px;cursor:pointer;font-size:.8rem;opacity:.5"
      >Compare selected</button>
      <span id="compare-hint" style="font-size:.78rem;color:#6b7280">Select 2+ runs to compare</span>
    </div>
    <div id="bench-compare" style="display:none;margin-bottom:1.2rem">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.6rem">
        <h2 style="font-size:.9rem;color:#6b7280;margin:0">Run Comparison</h2>
        <button onclick="clearComparison()"
          style="background:#1e1e2e;border:1px solid #2e2e3e;color:#9ca3af;padding:.25rem .7rem;border-radius:6px;cursor:pointer;font-size:.75rem"
        >Clear</button>
      </div>
      <table id="compare-table" style="width:100%;border-collapse:collapse;font-size:.82rem">
        <thead><tr id="compare-head"></tr></thead>
        <tbody id="compare-body"></tbody>
      </table>
    </div>
```

- [ ] **Step 3: Add checkbox column to the history table**

Find the Run History `<table>` header inside `<section id="bench-section">`:

```html
        <thead><tr>
          <th>Run ID</th><th>Task</th><th>A tests</th><th>B tests</th><th>C tests</th><th>RTK saving</th>
        </tr></thead>
```

Replace with:

```html
        <thead><tr>
          <th style="width:2rem"><input type="checkbox" id="check-all" onchange="toggleAllChecks(this)" title="Select all"></th>
          <th>Run ID</th><th>Task</th><th>A tests</th><th>B tests</th><th>C tests</th><th>RTK saving</th>
        </tr></thead>
```

- [ ] **Step 4: Add checkbox to each history row in renderBenchRuns**

Inside `renderBenchRuns`, find where each history row is built:

```javascript
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="run-label">${rid}</td>
      <td style="font-size:.75rem;color:#9ca3af">${taskSnip}</td>
```

Replace with:

```javascript
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="text-align:center"><input type="checkbox" class="run-check" data-run-id="${rid}" onchange="onRunCheckChange()"></td>
      <td class="run-label">${rid}</td>
      <td style="font-size:.75rem;color:#9ca3af">${taskSnip}</td>
```

- [ ] **Step 5: Add comparison JS functions**

Add these four functions at the end of the `<script>` block (before the final `load();` call):

```javascript
function onRunCheckChange() {
  const checked = [...document.querySelectorAll('.run-check:checked')];
  const runIds = [...new Set(checked.map(c => c.dataset.runId))];
  const btn = document.getElementById('compare-btn');
  const hint = document.getElementById('compare-hint');
  const enough = runIds.length >= 2;
  btn.disabled = !enough;
  btn.style.opacity = enough ? '1' : '.5';
  btn.style.cursor = enough ? 'pointer' : 'default';
  btn.textContent = enough ? `Compare ${runIds.length} runs` : 'Compare selected';
  hint.textContent = enough ? '' : runIds.length === 1 ? 'Select 1 more run' : 'Select 2+ runs to compare';
}

function toggleAllChecks(masterCb) {
  document.querySelectorAll('.run-check').forEach(cb => { cb.checked = masterCb.checked; });
  onRunCheckChange();
}

function clearComparison() {
  document.querySelectorAll('.run-check').forEach(cb => { cb.checked = false; });
  const master = document.getElementById('check-all');
  if (master) master.checked = false;
  document.getElementById('compare-btn').disabled = true;
  document.getElementById('compare-btn').style.opacity = '.5';
  document.getElementById('compare-btn').textContent = 'Compare selected';
  document.getElementById('compare-hint').textContent = 'Select 2+ runs to compare';
  document.getElementById('bench-compare').style.display = 'none';
}

function runComparison() {
  const checked = [...document.querySelectorAll('.run-check:checked')];
  const runIds = [...new Set(checked.map(c => c.dataset.runId))];
  if (runIds.length < 2) return;

  const panel = document.getElementById('bench-compare');
  panel.style.display = '';

  // One representative record per run_id: prefer the "A" variant (baseline/no-RTK)
  const runData = runIds.map(rid => {
    const grp = benchGroups[rid] || [];
    return grp.find(r => r.label && r.label.startsWith('A')) || grp[0] || {};
  });

  // Header row
  const headRow = document.getElementById('compare-head');
  headRow.innerHTML = '<th style="text-align:left;padding:.4rem .7rem;color:#6b7280;font-weight:500">Metric</th>' +
    runIds.map((rid, i) => {
      const rd = runData[i];
      const task = (rd.task || '').slice(0, 40);
      const isBase = i === 0 ? ' <span style="color:#a78bfa;font-size:.68rem">baseline</span>' : '';
      return `<th style="text-align:right;padding:.4rem .7rem;color:#6b7280;font-weight:500">` +
             `<span style="font-family:monospace;font-size:.75rem">${rid}</span>${isBase}<br>` +
             `<span style="color:#4b5563;font-size:.68rem">${task}…</span></th>`;
    }).join('');

  // Body rows
  const tbody = document.getElementById('compare-body');
  tbody.innerHTML = '';
  const baseline = runData[0];

  for (const [label, key, type] of ROWS) {
    if (!key) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="${runIds.length + 1}" style="background:#12121a;color:#6b7280;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;padding:.3rem .7rem">${label}</td>`;
      tbody.appendChild(tr);
      continue;
    }
    const tr = document.createElement('tr');
    const baseVal = baseline[key] ?? 0;
    const cells = runData.map((rd, i) => {
      const val = rd[key] ?? 0;
      let cell;
      if (i === 0) {
        cell = fmt(val);
      } else if (type === 'token') {
        cell = qCell(val, baseVal);
      } else if (type === 'qual-high') {
        cell = qQual(val, baseVal, true);
      } else {
        cell = qQual(val, baseVal, false);
      }
      return `<td style="text-align:right;padding:.4rem .7rem;font-family:monospace;border-bottom:1px solid #12121a">${cell}</td>`;
    }).join('');
    tr.innerHTML = `<td style="padding:.4rem .7rem;border-bottom:1px solid #12121a">${label}</td>${cells}`;
    tbody.appendChild(tr);
  }
}
```

- [ ] **Step 6: Run all tests to confirm nothing is broken**

```bash
cd /home/lgktg/claude-autonaumous
python3 -m pytest tests/test_bench_persist.py tests/test_bench_quality.py tests/test_bench_table.py -v 2>&1 | tail -25
```

Expected: all 17 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add bench_viewer.py
git commit -m "feat(bench-viewer): add run comparison UI — checkboxes in history table, side-by-side diff panel"
```

---

### Task 6: Final smoke-test

- [ ] **Step 1: Verify the full stack end-to-end**

```bash
cd /home/lgktg/claude-autonaumous
# Seed the DB with a synthetic record to verify the viewer renders it
python3 - <<'EOF'
from bench import _write_bench_results
_write_bench_results("20260413_000000", "Smoke test task", [
    {"label": "A (no RTK)", "use_rtk": False, "phases_enabled": False,
     "qwen_in": 12000, "qwen_out": 800, "tool_bytes": 45000,
     "claude_in": 500, "claude_out": 200, "wall_time_s": 120,
     "steps_completed": 4, "steps_failed": 0, "steps_total": 4,
     "tests_passed": 8, "tests_failed": 0},
    {"label": "B (RTK)", "use_rtk": True, "phases_enabled": False,
     "qwen_in": 10500, "qwen_out": 780, "tool_bytes": 38000,
     "claude_in": 500, "claude_out": 200, "wall_time_s": 108,
     "steps_completed": 4, "steps_failed": 0, "steps_total": 4,
     "tests_passed": 8, "tests_failed": 0},
])
_write_bench_results("20260413_010000", "Second smoke test task", [
    {"label": "A (no RTK)", "use_rtk": False, "phases_enabled": False,
     "qwen_in": 15000, "qwen_out": 900, "tool_bytes": 52000,
     "claude_in": 600, "claude_out": 220, "wall_time_s": 145,
     "steps_completed": 5, "steps_failed": 1, "steps_total": 6,
     "tests_passed": 6, "tests_failed": 2},
    {"label": "B (RTK)", "use_rtk": True, "phases_enabled": False,
     "qwen_in": 12000, "qwen_out": 860, "tool_bytes": 43000,
     "claude_in": 600, "claude_out": 220, "wall_time_s": 130,
     "steps_completed": 5, "steps_failed": 1, "steps_total": 6,
     "tests_passed": 6, "tests_failed": 2},
])
print("DB seeded with 2 run sets")
EOF

python3 bench_viewer.py &
sleep 1
curl -s http://localhost:8080/data | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} rows, run_ids: {list(set(r[\"run_id\"] for r in d))}')"
kill %1
```

Expected output: `4 rows, run_ids: ['20260413_000000', '20260413_010000']` (order may vary).

- [ ] **Step 2: Final commit**

```bash
git add .
git commit -m "chore: final integration verified — SQLite bench storage + comparison UI complete"
```
