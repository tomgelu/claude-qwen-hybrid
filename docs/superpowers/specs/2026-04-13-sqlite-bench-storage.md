# SQLite Bench Storage + Run Comparison

**Date:** 2026-04-13
**Status:** Approved

## Goal

Replace `benchmark_results.jsonl` with a SQLite database (`benchmark_results.db`) so bench runs are stored reliably and can be compared side-by-side in the viewer UI.

---

## Storage — `benchmark_results.db`

Single table `bench_runs`:

```sql
CREATE TABLE IF NOT EXISTS bench_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT    NOT NULL,
    task           TEXT    NOT NULL DEFAULT '',
    label          TEXT    NOT NULL DEFAULT '',
    use_rtk        INTEGER NOT NULL DEFAULT 0,   -- 0/1 (SQLite has no boolean)
    phases_enabled INTEGER NOT NULL DEFAULT 0,
    qwen_in        INTEGER NOT NULL DEFAULT 0,
    qwen_out       INTEGER NOT NULL DEFAULT 0,
    tool_bytes     INTEGER NOT NULL DEFAULT 0,
    claude_in      INTEGER NOT NULL DEFAULT 0,
    claude_out     INTEGER NOT NULL DEFAULT 0,
    steps_completed INTEGER NOT NULL DEFAULT 0,
    steps_failed    INTEGER NOT NULL DEFAULT 0,
    steps_total     INTEGER NOT NULL DEFAULT 0,
    tests_passed    INTEGER NOT NULL DEFAULT 0,
    tests_failed    INTEGER NOT NULL DEFAULT 0,
    wall_time_s     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

The DB file lives at `<repo-root>/benchmark_results.db` (same location as the old JSONL file). It is created automatically on first write; no manual migration step is required.

**JSONL migration:** If `benchmark_results.jsonl` exists at write time, its records are imported into the DB and the file is deleted. This happens once, transparently, inside `_write_bench_results()`.

---

## `bench.py` — `_write_bench_results()` rewrite

**Signature is unchanged:**
```python
def _write_bench_results(run_id, task, stats_list, out_path=None) -> None
```

`out_path` override now points to a temp `.db` file in tests (not `.jsonl`). All existing tests remain valid — only the storage mechanism changes, not the interface.

**Implementation:**
1. `sqlite3.connect(db_path)` — creates file + schema if missing
2. `INSERT INTO bench_runs (...)` one row per stats dict
3. Booleans stored as `int(bool(val))`

**JSONL migration** (inside `_write_bench_results`, runs once):
1. If `_JSONL_FILE` exists, read all valid JSON lines
2. For each record with `model_type == "bench_run"`, insert into DB (skip duplicates via `INSERT OR IGNORE` on `run_id + label`)
3. Delete `_JSONL_FILE`

---

## `bench_viewer.py` — `/data` endpoint

`do_GET` for `/data` changes from:
```python
rows = [json.loads(line) for line in RESULTS_FILE.read_text().splitlines()]
```
to:
```python
conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row
rows = [dict(r) for r in conn.execute("SELECT * FROM bench_runs ORDER BY created_at")]
conn.close()
```

Return shape is identical — a JSON array of dicts. All existing JS is untouched.

---

## Viewer — Comparison UI

**History table checkbox column:**
- New first column with a checkbox `<input type="checkbox" class="run-check" data-run-id="...">` per row
- Header cell contains a "select all" checkbox

**"Compare Selected" button:**
- Rendered above the history table, disabled by default
- Enabled (via JS event listener on `.run-check` change) when ≥ 2 unique `run_id` values are checked
- Label: `Compare N runs` (updates dynamically)

**Comparison panel (`#bench-compare`):**
- Hidden by default (`display:none`), shown below history table when comparison fires
- Layout: metrics as rows, selected runs as columns (one column per checked `run_id`)
- Column header: `run_id` + task snippet
- Rows: same `ROWS` definition as the existing comparison table (Token Efficiency, Output Quality, Run Info sections)
- Delta cells: first selected run is baseline; subsequent runs show `▼`/`▲` % using existing `qCell`/`qQual` helpers
- "Clear" button resets checkboxes and hides the panel

---

## Cleanup

**`.gitignore` additions:**
```
benchmark_results.db
benchmark_results.jsonl
tasks.db
__pycache__/
.pytest_cache/
.superpowers/
```

**Files to delete:**
- `benchmark_results.jsonl` (if present — migrated to DB automatically)
- `.superpowers/brainstorm/` scratch files from failed visual companion session

---

## Test Updates

`tests/test_bench_persist.py` — two tests use `out_path` pointing to a temp `.jsonl` file. Update them to use a temp `.db` path instead. Assertions on schema fields are unchanged.

---

## Out of Scope

- No new HTTP endpoints
- No server-side diff computation
- No authentication or multi-user support
- No schema versioning / migrations beyond the one-time JSONL import
