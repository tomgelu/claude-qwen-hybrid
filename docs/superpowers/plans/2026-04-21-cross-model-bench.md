# Cross-Model Benchmark Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `bench_compare.py` script that stops/starts vLLM Docker containers to run a 4-run benchmark (35B no-RTK, 35B RTK, 80B no-RTK, 80B RTK) sequentially, storing results linked by a shared `compare_id`, then shows a cross-model comparison in `bench_viewer.py`.

**Architecture:** `bench_compare.py` orchestrates Docker container swaps and calls `bench.py` as a subprocess with `--tag` and `--compare-id` args. `bench.py` gains two new DB columns (`model_label`, `compare_id`). `bench_viewer.py` adds a Model Comparison section that groups by `compare_id` and renders a 4-column verdict table.

**Tech Stack:** Python 3.12, SQLite, Docker CLI (`docker compose`, `docker run`), Chart.js (already in viewer)

---

## File Map

| File | Action | What changes |
|---|---|---|
| `bench.py` | Modify | Add `--tag`/`--compare-id` CLI args; add `model_label`/`compare_id` columns to schema and insert |
| `bench_compare.py` | Create | Full orchestrator: stop/start Docker, wait for health, invoke bench.py per model |
| `bench_viewer.py` | Modify | New "Model Comparison" HTML section + `renderModelComparison()` JS function |

---

## Task 1: Add `model_label` and `compare_id` to bench.py

**Files:**
- Modify: `bench.py`

- [ ] **Step 1: Add columns to `_CREATE_TABLE`**

In `bench.py`, replace the `_CREATE_TABLE` string to add the two new columns at the end:

```python
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
    model_label     TEXT    NOT NULL DEFAULT '',
    compare_id      TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""
```

- [ ] **Step 2: Add DB migration for existing rows**

In `_write_bench_results`, after `conn.execute(_CREATE_TABLE)` and before the JSONL migration block, add:

```python
        # Migrate existing DBs that predate model_label/compare_id columns
        for col, defn in [
            ("model_label", "TEXT NOT NULL DEFAULT ''"),
            ("compare_id",  "TEXT NOT NULL DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE bench_runs ADD COLUMN {col} {defn}")
            except sqlite3.OperationalError:
                pass  # column already exists
```

- [ ] **Step 3: Update `_INSERT_ROW` and the insert call**

Replace `_INSERT_ROW`:

```python
_INSERT_ROW = """
INSERT INTO bench_runs
    (run_id, task, label, use_rtk, phases_enabled,
     qwen_in, qwen_out, tool_bytes, claude_in, claude_out,
     steps_completed, steps_failed, steps_total,
     tests_passed, tests_failed, wall_time_s,
     model_label, compare_id)
VALUES
    (:run_id, :task, :label, :use_rtk, :phases_enabled,
     :qwen_in, :qwen_out, :tool_bytes, :claude_in, :claude_out,
     :steps_completed, :steps_failed, :steps_total,
     :tests_passed, :tests_failed, :wall_time_s,
     :model_label, :compare_id)
"""
```

In `_write_bench_results`, update the `conn.execute(_INSERT_ROW, {...})` call to include:

```python
                "model_label":     stats.get("model_label", ""),
                "compare_id":      stats.get("compare_id", ""),
```

- [ ] **Step 4: Add `--tag` and `--compare-id` CLI args to `main()`**

In `main()`, after the existing `parser.add_argument("--phases", ...)` line, add:

```python
    parser.add_argument("--tag",        default="",
                        help="Model label stored in DB (e.g. 35b, 80b)")
    parser.add_argument("--compare-id", default="", dest="compare_id",
                        help="Links this run to a cross-model comparison set")
```

- [ ] **Step 5: Thread `model_label` and `compare_id` through to persist_stats**

In `main()`, replace the `persist_stats` list and `_write_bench_results` call:

```python
    persist_stats = [
        {**avg_a, "label": f"A (no RTK){avg_sfx_label}",
         "model_label": args.tag, "compare_id": args.compare_id},
        {**avg_b, "label": f"B (RTK){avg_sfx_label}",
         "model_label": args.tag, "compare_id": args.compare_id},
    ]
    if all_c:
        persist_stats.append({**avg_c, "label": f"C (RTK+phases){avg_sfx_label}",
                               "model_label": args.tag, "compare_id": args.compare_id})
    _write_bench_results(run_id, task, persist_stats)
```

- [ ] **Step 6: Verify**

```bash
cd /home/lgktg/claude-autonaumous
python3 -c "import bench; print('import OK')"
python3 -c "
import sqlite3, bench
conn = sqlite3.connect('/tmp/test_bench.db')
conn.execute(bench._CREATE_TABLE)
conn.commit()
cols = [r[1] for r in conn.execute('PRAGMA table_info(bench_runs)').fetchall()]
assert 'model_label' in cols, cols
assert 'compare_id' in cols, cols
print('schema OK:', cols)
conn.close()
"
```

Expected: `schema OK: [..., 'model_label', 'compare_id', ...]`

- [ ] **Step 7: Commit**

```bash
git add bench.py
git commit -m "feat(bench): add model_label and compare_id columns for cross-model tracking"
```

---

## Task 2: Create `bench_compare.py`

**Files:**
- Create: `bench_compare.py`

- [ ] **Step 1: Create the file**

```python
#!/usr/bin/env python3
"""
bench_compare.py — cross-model benchmark: 35B vs 80B, each with and without RTK.

Stops the current vLLM container, starts the target model, waits for health,
runs bench.py A+B, then repeats for the second model. Results are linked in
the DB by a shared compare_id for cross-model display in bench_viewer.

Usage:
    python3 bench_compare.py
    python3 bench_compare.py "your task here"
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
HEALTH_URL = "http://localhost:8000/health"

# Model configs — order determines run sequence (35B first, cheaper/faster warmup)
MODEL_CONFIGS = [
    {
        "tag":              "35b",
        "model_name":       "Qwen/Qwen3.6-35B-A3B",
        "local_model_name": "Qwen/Qwen3.6-35B-A3B",
        "health_timeout":   300,
        "start_mode":       "compose",
        "vllm_extra_args":  (
            "--trust-remote-code --enforce-eager "
            "--enable-auto-tool-choice --tool-call-parser qwen3_xml "
            "--enable-prefix-caching"
        ),
    },
    {
        "tag":              "80b",
        "model_name":       "nvidia/Qwen3-Next-80B-A3B-Instruct-NVFP4",
        "local_model_name": "qwen3-next-80b",
        "health_timeout":   600,
        "start_mode":       "docker_run",
    },
]


def stop_servers() -> None:
    """Stop all running vLLM containers (both compose and standalone)."""
    print("  [compare] Stopping vLLM servers...", flush=True)
    subprocess.run(["docker", "stop", "vllm-server"], capture_output=True)
    subprocess.run(
        ["docker", "compose", "down", "vllm"],
        capture_output=True, cwd=str(HERE),
    )
    time.sleep(3)


def start_35b(cfg: dict) -> None:
    """Start 35B via docker compose with model-specific env vars."""
    env = {
        **os.environ,
        "VLLM_MODEL":      cfg["model_name"],
        "VLLM_EXTRA_ARGS": cfg["vllm_extra_args"],
    }
    subprocess.run(
        ["docker", "compose", "up", "-d", "vllm"],
        env=env, cwd=str(HERE), check=True,
    )


def start_80b(cfg: dict) -> None:
    """Start 80B via docker run -d using the NVFP4 kernel image."""
    home = Path.home()
    subprocess.run([
        "docker", "run", "-d",
        "--name", "vllm-server",
        "--gpus", "all",
        "--ipc=host",
        "--security-opt", "seccomp=unconfined",
        "--ulimit", "memlock=-1",
        "--ulimit", "stack=67108864",
        "-p", "127.0.0.1:8000:8000",
        "-v", f"{home}/.cache/huggingface:/root/.cache/huggingface",
        "-v", f"{home}/.cache/vllm:/root/.cache/vllm",
        "-v", f"{home}/.cache/triton:/root/.cache/triton",
        "-v", (
            f"{home}/sglang/patches/nvfp4.py:"
            "/app/vllm/vllm/model_executor/layers/fused_moe/oracle/nvfp4.py:ro"
        ),
        "-e", f"MODEL={cfg['model_name']}",
        "-e", "PORT=8000",
        "-e", "HOST=0.0.0.0",
        "-e", "GPU_MEMORY_UTIL=0.88",
        "-e", "MAX_MODEL_LEN=32768",
        "-e", "MAX_NUM_SEQS=16",
        "-e", (
            "VLLM_EXTRA_ARGS=--trust-remote-code "
            "--served-model-name qwen3-next-80b "
            "--enforce-eager --enable-auto-tool-choice "
            "--tool-call-parser qwen3_xml"
        ),
        "avarok/dgx-vllm-nvfp4-kernel:v23", "serve",
    ], check=True)


def wait_for_health(timeout: int, tag: str) -> None:
    """Poll GET /health until 200 or timeout. Raises TimeoutError on failure."""
    print(f"  [compare] Waiting for {tag} server (up to {timeout}s)...", flush=True)
    deadline = time.time() + timeout
    dots = 0
    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["curl", "-sf", "--max-time", "4", HEALTH_URL],
                capture_output=True,
            )
            if result.returncode == 0:
                print(f"\n  [compare] {tag} server is healthy.", flush=True)
                return
        except Exception:
            pass
        time.sleep(5)
        dots += 1
        if dots % 6 == 0:
            elapsed = int(time.time() - (deadline - timeout))
            print(f"  [compare] Still waiting... {elapsed}s elapsed", flush=True)
    raise TimeoutError(f"{tag} server did not become healthy within {timeout}s")


def run_bench(task: str, tag: str, compare_id: str) -> None:
    """Invoke bench.py as a subprocess with model tag and compare_id."""
    print(f"\n  [compare] Running bench for {tag}...", flush=True)
    subprocess.run(
        [
            sys.executable, str(HERE / "bench.py"),
            task, "--tag", tag, "--compare-id", compare_id,
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-model benchmark: 35B vs 80B, each with/without RTK"
    )
    parser.add_argument("task", nargs="?", default=None, help="Task description")
    args = parser.parse_args()

    # Import DEFAULT_TASK from bench without running its main()
    sys.path.insert(0, str(HERE))
    from bench import DEFAULT_TASK
    task = args.task or DEFAULT_TASK

    compare_id = "cmp_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    print("Cross-model benchmark: 35B vs 80B")
    print(f"Task:       {task[:80]}{'…' if len(task) > 80 else ''}")
    print(f"Compare ID: {compare_id}")
    print(f"Sequence:   35B (A+B)  →  80B (A+B)\n", flush=True)

    for cfg in MODEL_CONFIGS:
        tag = cfg["tag"]
        print(f"\n{'='*60}")
        print(f"  MODEL: {tag}  ({cfg['model_name']})")
        print(f"{'='*60}", flush=True)

        stop_servers()

        if cfg["start_mode"] == "compose":
            start_35b(cfg)
        else:
            start_80b(cfg)

        wait_for_health(cfg["health_timeout"], tag)

        # Tell bench.py which model name to use for the API call
        os.environ["LOCAL_MODEL_NAME"] = cfg["local_model_name"]
        os.environ["LOCAL_MODEL_URL"]  = "http://127.0.0.1:8000/v1/chat/completions"

        run_bench(task, tag, compare_id)

    stop_servers()
    print(f"\n{'='*60}")
    print(f"✓ Cross-model benchmark complete.")
    print(f"  Compare ID: {compare_id}")
    print(f"  Open bench_viewer → Model Comparison section to see results.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast, pathlib; ast.parse(pathlib.Path('bench_compare.py').read_text()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add bench_compare.py
git commit -m "feat: add bench_compare.py for sequential 35B vs 80B cross-model benchmark"
```

---

## Task 3: Add Model Comparison section to bench_viewer.py

**Files:**
- Modify: `bench_viewer.py`

- [ ] **Step 1: Add the HTML section placeholder**

In `bench_viewer.py`, in the `HTML` string, add a new section between `<main>` and `<div class="cards" id="cards">`:

```html
  <section id="model-cmp-section" style="display:none;margin-bottom:1.5rem">
    <h2>Model Comparison</h2>
    <div id="model-cmp-selector" style="margin-bottom:.75rem;font-size:.8rem;color:#6b7280"></div>
    <table id="model-cmp-table" style="width:100%;border-collapse:collapse;font-size:.82rem">
      <thead><tr id="model-cmp-head"></tr></thead>
      <tbody id="model-cmp-body"></tbody>
    </table>
    <div id="model-cmp-verdict" style="margin-top:1rem"></div>
  </section>
```

Place it directly after `<div id="summary-banner" class="neu" style="display:none"></div>`.

- [ ] **Step 2: Add `renderModelComparison()` JS function**

In the `<script>` block, add this function before `renderSummary`:

```javascript
function renderModelComparison(benchRuns) {
  const section = document.getElementById('model-cmp-section');
  // Group by compare_id — skip empty compare_ids
  const groups = {};
  for (const r of benchRuns) {
    if (!r.compare_id) continue;
    if (!groups[r.compare_id]) groups[r.compare_id] = [];
    groups[r.compare_id].push(r);
  }
  const cmpIds = Object.keys(groups).sort().reverse();
  if (!cmpIds.length) { section.style.display = 'none'; return; }
  section.style.display = '';

  // Use most recent comparison
  const latest = groups[cmpIds[0]];

  // Build selector if multiple comparisons exist
  const sel = document.getElementById('model-cmp-selector');
  if (cmpIds.length > 1) {
    sel.innerHTML = 'Comparison: ' + cmpIds.map((id, i) =>
      `<span style="cursor:pointer;color:${i===0?'#a78bfa':'#6b7280'};margin-right:.5rem"
        onclick="showComparison('${esc(id)}')">${esc(id)}</span>`
    ).join('');
  } else {
    sel.innerHTML = `<span style="font-family:monospace">${esc(cmpIds[0])}</span>`;
  }

  // Find the 4 runs: 35b no-rtk, 35b rtk, 80b no-rtk, 80b rtk
  const find = (tag, rtk) => latest.find(r =>
    r.model_label === tag && (rtk ? r.use_rtk : !r.use_rtk)
  ) || {};

  const cols = [
    { label: '35B  no RTK', run: find('35b', false) },
    { label: '35B  RTK',    run: find('35b', true)  },
    { label: '80B  no RTK', run: find('80b', false) },
    { label: '80B  RTK',    run: find('80b', true)  },
  ].filter(c => Object.keys(c.run).length);

  if (!cols.length) { section.style.display = 'none'; return; }

  // Header
  const headRow = document.getElementById('model-cmp-head');
  headRow.innerHTML =
    '<th style="text-align:left;padding:.4rem .7rem;color:#6b7280;font-weight:500">Metric</th>' +
    cols.map(c =>
      `<th style="text-align:right;padding:.4rem .7rem;color:#6b7280;font-weight:500">${esc(c.label)}</th>`
    ).join('');

  // Body — use same ROWS definition as the rest of the viewer
  const tbody = document.getElementById('model-cmp-body');
  tbody.innerHTML = '';
  const baseRun = cols[0].run;
  for (const [label, key, type] of ROWS) {
    if (!key) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="${cols.length + 1}"
        style="background:#12121a;color:#6b7280;font-size:.72rem;text-transform:uppercase;
               letter-spacing:.05em;padding:.3rem .7rem">${label}</td>`;
      tbody.appendChild(tr);
      continue;
    }
    const tr = document.createElement('tr');
    const cells = cols.map((c, i) => {
      const val     = c.run[key] ?? 0;
      const baseVal = baseRun[key] ?? 0;
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
      return `<td style="text-align:right;padding:.4rem .7rem;font-family:monospace;
                border-bottom:1px solid #12121a">${cell}</td>`;
    }).join('');
    tr.innerHTML = `<td style="padding:.4rem .7rem;border-bottom:1px solid #12121a">${label}</td>${cells}`;
    tbody.appendChild(tr);
  }

  // Verdict
  renderModelVerdict(cols, document.getElementById('model-cmp-verdict'));
}

function renderModelVerdict(cols, el) {
  // Pick best model per dimension (lower tokens/time = better; higher tests = better)
  const dimensions = [
    { name: 'Token efficiency', key: 'qwen_in',      lowerBetter: true  },
    { name: 'Speed',            key: 'wall_time_s',  lowerBetter: true  },
    { name: 'Quality',          key: 'tests_passed', lowerBetter: false },
  ];

  const lines = dimensions.map(dim => {
    const vals = cols.map(c => ({ label: c.label, val: c.run[dim.key] ?? 0 }));
    const best = vals.reduce((a, b) =>
      dim.lowerBetter ? (a.val <= b.val ? a : b) : (a.val >= b.val ? a : b)
    );
    const worst = vals.reduce((a, b) =>
      dim.lowerBetter ? (a.val >= b.val ? a : b) : (a.val <= b.val ? a : b)
    );
    const diff = worst.val > 0
      ? Math.abs((best.val - worst.val) / worst.val * 100).toFixed(1)
      : '0';
    const cls = best.label.includes('80B') ? 'delta-pos' : '#7dd3fc';
    return `<span style="color:${cls}">● ${dim.name}:</span> ` +
           `<strong>${esc(best.label)}</strong> wins by ${diff}%`;
  });

  el.innerHTML = `
    <div style="background:#12121a;border-radius:6px;padding:.8rem 1rem;font-size:.82rem;line-height:2">
      ${lines.join('<br>')}
    </div>`;
}
```

- [ ] **Step 3: Wire `renderModelComparison` into `render()`**

In the `render()` function, add the call right after `renderSummary(benchRuns)`:

```javascript
  renderModelComparison(benchRuns);
```

- [ ] **Step 4: Restart the viewer and verify**

```bash
pkill -f "bench_viewer.py 9090" 2>/dev/null; sleep 1
python3 /home/lgktg/claude-autonaumous/bench_viewer.py 9090 &
sleep 2 && curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:9090
```

Expected: `HTTP 200`

Open http://localhost:9090 — the Model Comparison section should be hidden (no compare_id data yet). It will appear after running `bench_compare.py`.

- [ ] **Step 5: Commit**

```bash
git add bench_viewer.py
git commit -m "feat(bench-viewer): add Model Comparison section for cross-model results"
```

---

## Self-Review

**Spec coverage:**
- ✓ `bench_compare.py` stops/starts Docker per model
- ✓ 35B via docker compose, 80B via docker run with nvfp4 patch
- ✓ Health poll with per-model timeouts (300s / 600s)
- ✓ `--tag` and `--compare-id` args on bench.py
- ✓ `model_label` and `compare_id` columns in DB
- ✓ Migration for existing DB rows
- ✓ Model Comparison section in viewer with 4-column table
- ✓ Plain-English verdict per dimension (tokens, speed, quality)

**No placeholders:** All code is complete. No TBDs.

**Type consistency:**
- `model_label` used consistently across bench.py schema, insert, and viewer JS field access
- `compare_id` used consistently across bench.py, bench_compare.py, and viewer grouping logic
- `find('35b', false)` matches `model_label = "35b"` stored by `--tag 35b`
