# Score de Cushman (CIWA-Ar) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a responsive single-page web app for scoring alcohol withdrawal severity (CIWA-Ar / Score de Cushman) with a Flask + SQLite backend.

**Architecture:** Plain HTML/CSS/JS frontend served by Flask; clinician taps buttons to score 10 criteria, live total updates in JS, "Enregistrer" posts to Flask API which writes to SQLite; collapsible history panel reads from the same API.

**Tech Stack:** Python 3, Flask, SQLite (stdlib), plain HTML/CSS/JS (no build step)

---

## File Map

| Path | Responsibility |
|------|---------------|
| `cushman/requirements.txt` | Python deps (flask only) |
| `cushman/db.py` | SQLite connection, schema creation, save/fetch helpers |
| `cushman/app.py` | Flask app — serves static page + 2 REST endpoints |
| `cushman/static/index.html` | Single-page markup: criteria rows + history panel |
| `cushman/static/style.css` | Responsive mobile-first styles |
| `cushman/static/app.js` | CIWA-Ar scoring logic, live updates, API calls |
| `cushman/tests/__init__.py` | Empty |
| `cushman/tests/test_db.py` | Unit tests for db.py helpers |
| `cushman/tests/test_app.py` | Flask test-client tests for API routes |

---

## Task 1: Project scaffold

**Files:**
- Create: `cushman/requirements.txt`
- Create: `cushman/tests/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p cushman/static cushman/tests
touch cushman/__init__.py cushman/tests/__init__.py
```

- [ ] **Step 2: Write requirements.txt**

Create `cushman/requirements.txt`:

```
flask==3.1.0
pytest==8.3.5
```

- [ ] **Step 3: Write conftest.py (makes `cushman` importable by pytest)**

Create `conftest.py` at the project root (parent of `cushman/`):

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
```

- [ ] **Step 4: Install deps**

```bash
pip install -r cushman/requirements.txt
```

Expected: `Successfully installed flask-3.1.0` (or already satisfied)

- [ ] **Step 5: Commit**

```bash
git add cushman/ conftest.py
git commit -m "chore(cushman): scaffold project structure"
```

---

## Task 2: Database layer

**Files:**
- Create: `cushman/db.py`
- Create: `cushman/tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Create `cushman/tests/test_db.py`:

```python
import json
import os
import tempfile
import pytest
from cushman import db as db_module


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_path


def test_init_creates_table(tmp_db):
    import sqlite3
    con = sqlite3.connect(tmp_db)
    cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='assessments'")
    assert cur.fetchone() is not None
    con.close()


def test_save_and_fetch(tmp_db):
    scores = [2, 1, 0, 3, 1, 0, 0, 1, 2, 1]
    total = sum(scores)
    db_module.save_assessment(scores, total, "modéré")
    rows = db_module.get_assessments(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert json.loads(row["scores"]) == scores
    assert row["total"] == total
    assert row["severity"] == "modéré"
    assert "timestamp" in row
    assert "id" in row


def test_get_assessments_returns_newest_first(tmp_db):
    db_module.save_assessment([0]*10, 0, "léger")
    db_module.save_assessment([7]*9 + [4], 67, "sévère")
    rows = db_module.get_assessments(limit=10)
    assert rows[0]["total"] == 67
    assert rows[1]["total"] == 0


def test_get_assessments_respects_limit(tmp_db):
    for i in range(5):
        db_module.save_assessment([i]*10, i*10, "léger")
    rows = db_module.get_assessments(limit=3)
    assert len(rows) == 3
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd cushman && python -m pytest tests/test_db.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` (db.py doesn't exist yet)

- [ ] **Step 3: Write db.py**

Create `cushman/db.py`:

```python
import json
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "cushman.db")


def _connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = _connect()
    con.execute("""
        CREATE TABLE IF NOT EXISTS assessments (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            scores    TEXT NOT NULL,
            total     INTEGER NOT NULL,
            severity  TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def save_assessment(scores: list[int], total: int, severity: str) -> int:
    con = _connect()
    cur = con.execute(
        "INSERT INTO assessments (scores, total, severity) VALUES (?, ?, ?)",
        (json.dumps(scores), total, severity),
    )
    con.commit()
    row_id = cur.lastrowid
    con.close()
    return row_id


def get_assessments(limit: int = 50) -> list[dict]:
    con = _connect()
    cur = con.execute(
        "SELECT id, timestamp, scores, total, severity FROM assessments ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd cushman && python -m pytest tests/test_db.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add cushman/db.py cushman/tests/test_db.py
git commit -m "feat(cushman): add SQLite database layer with tests"
```

---

## Task 3: Flask API

**Files:**
- Create: `cushman/app.py`
- Create: `cushman/tests/test_app.py`

- [ ] **Step 1: Write failing tests**

Create `cushman/tests/test_app.py`:

```python
import json
import os
import tempfile
import pytest
import cushman.db as db_module


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()

    from cushman.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_get_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"html" in r.data.lower()


def test_post_assessment_valid(client):
    payload = {
        "scores": [2, 1, 0, 3, 1, 0, 0, 1, 2, 1],
        "total": 11,
        "severity": "modéré",
    }
    r = client.post("/api/assessments", json=payload)
    assert r.status_code == 201
    data = json.loads(r.data)
    assert "id" in data


def test_post_assessment_missing_field(client):
    r = client.post("/api/assessments", json={"total": 5})
    assert r.status_code == 400


def test_post_assessment_wrong_scores_length(client):
    r = client.post("/api/assessments", json={
        "scores": [1, 2, 3],
        "total": 6,
        "severity": "léger",
    })
    assert r.status_code == 400


def test_get_assessments_empty(client):
    r = client.get("/api/assessments")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data == []


def test_get_assessments_returns_saved(client):
    client.post("/api/assessments", json={
        "scores": [1]*9 + [1],
        "total": 10,
        "severity": "modéré",
    })
    r = client.get("/api/assessments")
    data = json.loads(r.data)
    assert len(data) == 1
    assert data[0]["total"] == 10
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd cushman && python -m pytest tests/test_app.py -v
```

Expected: `ImportError` (app.py doesn't exist yet)

- [ ] **Step 3: Write app.py**

Create `cushman/app.py`:

```python
import os
from flask import Flask, jsonify, request, send_from_directory
import cushman.db as db

app = Flask(__name__, static_folder="static")

DB_INITIALIZED = False


@app.before_request
def ensure_db():
    global DB_INITIALIZED
    if not DB_INITIALIZED:
        db.init_db()
        DB_INITIALIZED = True


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/assessments")
def create_assessment():
    body = request.get_json(silent=True) or {}
    scores = body.get("scores")
    total = body.get("total")
    severity = body.get("severity")

    if scores is None or total is None or severity is None:
        return jsonify({"error": "scores, total, and severity are required"}), 400
    if not isinstance(scores, list) or len(scores) != 10:
        return jsonify({"error": "scores must be a list of 10 integers"}), 400

    row_id = db.save_assessment(scores, int(total), str(severity))
    return jsonify({"id": row_id}), 201


@app.get("/api/assessments")
def list_assessments():
    rows = db.get_assessments(limit=50)
    return jsonify(rows), 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)
```

- [ ] **Step 4: Run all tests — verify they pass**

```bash
cd cushman && python -m pytest tests/ -v
```

Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add cushman/app.py cushman/tests/test_app.py
git commit -m "feat(cushman): add Flask API with route tests"
```

---

## Task 4: HTML page structure

**Files:**
- Create: `cushman/static/index.html`

- [ ] **Step 1: Write index.html**

Create `cushman/static/index.html`:

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Score de Cushman</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <h1>Score de Cushman <span class="subtitle">(CIWA-Ar)</span></h1>
  </header>

  <main>
    <div id="error-banner" class="error-banner hidden">
      Erreur de connexion — score non enregistré
    </div>

    <section id="calculator">
      <div id="criteria-list">
        <!-- Populated by app.js -->
      </div>

      <div id="score-summary">
        <span class="score-label">Total :</span>
        <span id="total-display" class="score-value">0</span>
        <span id="severity-badge" class="badge badge-leger">Sevrage léger</span>
      </div>

      <button id="save-btn" class="btn-primary">Enregistrer</button>
    </section>

    <section id="history-section">
      <button id="history-toggle" class="btn-secondary">
        Afficher l'historique <span id="toggle-arrow">▼</span>
      </button>
      <div id="history-panel" class="hidden">
        <table id="history-table">
          <thead>
            <tr>
              <th>Date / Heure</th>
              <th>Total</th>
              <th>Sévérité</th>
            </tr>
          </thead>
          <tbody id="history-body">
            <!-- Populated by app.js -->
          </tbody>
        </table>
        <p id="history-empty" class="hidden">Aucune évaluation enregistrée</p>
      </div>
    </section>
  </main>

  <script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Verify HTML renders**

```bash
python -m cushman.app
```

Open `http://localhost:5000` — page should load (unstyled, no JS behaviour yet).
Stop server with Ctrl+C.

- [ ] **Step 3: Commit**

```bash
git add cushman/static/index.html
git commit -m "feat(cushman): add HTML page structure"
```

---

## Task 5: CSS styles

**Files:**
- Create: `cushman/static/style.css`

- [ ] **Step 1: Write style.css**

Create `cushman/static/style.css`:

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: system-ui, -apple-system, sans-serif;
  background: #f5f6fa;
  color: #222;
  min-height: 100vh;
}

header {
  background: #1a73e8;
  color: white;
  padding: 1rem 1.5rem;
}
header h1 { font-size: 1.4rem; font-weight: 700; }
.subtitle { font-size: 1rem; font-weight: 400; opacity: 0.85; }

main {
  max-width: 700px;
  margin: 1.5rem auto;
  padding: 0 1rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* Error banner */
.error-banner {
  background: #fdecea;
  color: #b71c1c;
  border: 1px solid #f5c6cb;
  border-radius: 6px;
  padding: 0.75rem 1rem;
  font-size: 0.95rem;
}
.hidden { display: none !important; }

/* Criteria */
#criteria-list { display: flex; flex-direction: column; gap: 0.75rem; }

.criterion-row {
  background: white;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.criterion-label {
  font-size: 0.9rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
  color: #444;
}
.btn-group { display: flex; flex-wrap: wrap; gap: 0.4rem; }

.score-btn {
  min-width: 2.4rem;
  height: 2.4rem;
  border: 2px solid #d0d5dd;
  border-radius: 6px;
  background: white;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
  color: #444;
}
.score-btn:hover { border-color: #1a73e8; color: #1a73e8; }
.score-btn.selected {
  background: #1a73e8;
  border-color: #1a73e8;
  color: white;
}

/* Score summary */
#score-summary {
  display: flex;
  align-items: center;
  gap: 1rem;
  background: white;
  border-radius: 8px;
  padding: 1rem 1.25rem;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.score-label { font-size: 1rem; color: #666; }
.score-value { font-size: 2rem; font-weight: 700; min-width: 2.5rem; }

/* Severity badges */
.badge {
  padding: 0.35rem 0.8rem;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 600;
  margin-left: auto;
}
.badge-leger   { background: #e6f4ea; color: #2e7d32; }
.badge-modere  { background: #fff3e0; color: #e65100; }
.badge-severe  { background: #fdecea; color: #b71c1c; }

/* Buttons */
.btn-primary {
  width: 100%;
  padding: 0.9rem;
  background: #1a73e8;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1.05rem;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-primary:hover { background: #1558b0; }

.btn-secondary {
  width: 100%;
  padding: 0.75rem;
  background: white;
  color: #444;
  border: 1px solid #d0d5dd;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
}
.btn-secondary:hover { background: #f0f4ff; }

/* History */
#history-section { display: flex; flex-direction: column; gap: 0.75rem; }
#history-panel {
  background: white;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  overflow: hidden;
}
#history-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
#history-table th, #history-table td {
  padding: 0.65rem 1rem;
  text-align: left;
  border-bottom: 1px solid #f0f0f0;
}
#history-table th { background: #f8f9fb; font-weight: 700; color: #555; }
#history-empty { padding: 1rem; color: #888; font-size: 0.9rem; }

@media (max-width: 480px) {
  .score-btn { min-width: 2.1rem; height: 2.1rem; font-size: 0.85rem; }
  .score-value { font-size: 1.6rem; }
}
```

- [ ] **Step 2: Commit**

```bash
git add cushman/static/style.css
git commit -m "feat(cushman): add responsive mobile-first CSS"
```

---

## Task 6: JavaScript — scoring logic + API calls

**Files:**
- Create: `cushman/static/app.js`

- [ ] **Step 1: Write app.js**

Create `cushman/static/app.js`:

```javascript
const CRITERIA = [
  { label: "Nausée / Vomissements",   max: 7 },
  { label: "Tremblements",            max: 7 },
  { label: "Sueurs paroxystiques",    max: 7 },
  { label: "Anxiété",                 max: 7 },
  { label: "Agitation",               max: 7 },
  { label: "Troubles tactiles",       max: 7 },
  { label: "Troubles auditifs",       max: 7 },
  { label: "Troubles visuels",        max: 7 },
  { label: "Céphalées",               max: 7 },
  { label: "Orientation / Conscience",max: 4 },
];

// Current score for each criterion (index matches CRITERIA)
const scores = new Array(CRITERIA.length).fill(0);

function getSeverity(total) {
  if (total <= 7)  return { label: "Sevrage léger",  cls: "badge-leger" };
  if (total <= 15) return { label: "Sevrage modéré", cls: "badge-modere" };
  return                  { label: "Sevrage sévère", cls: "badge-severe" };
}

function updateSummary() {
  const total = scores.reduce((a, b) => a + b, 0);
  document.getElementById("total-display").textContent = total;
  const { label, cls } = getSeverity(total);
  const badge = document.getElementById("severity-badge");
  badge.textContent = label;
  badge.className = `badge ${cls}`;
}

function buildCriteria() {
  const container = document.getElementById("criteria-list");
  CRITERIA.forEach((criterion, i) => {
    const row = document.createElement("div");
    row.className = "criterion-row";

    const labelEl = document.createElement("div");
    labelEl.className = "criterion-label";
    labelEl.textContent = `${i + 1}. ${criterion.label}`;
    row.appendChild(labelEl);

    const btnGroup = document.createElement("div");
    btnGroup.className = "btn-group";

    for (let v = 0; v <= criterion.max; v++) {
      const btn = document.createElement("button");
      btn.className = "score-btn" + (v === 0 ? " selected" : "");
      btn.textContent = v;
      btn.setAttribute("aria-label", `${criterion.label}: ${v}`);
      btn.addEventListener("click", () => {
        scores[i] = v;
        // Update button states for this criterion
        btnGroup.querySelectorAll(".score-btn").forEach((b, idx) => {
          b.classList.toggle("selected", idx === v);
        });
        updateSummary();
      });
      btnGroup.appendChild(btn);
    }

    row.appendChild(btnGroup);
    container.appendChild(row);
  });
}

function resetForm() {
  scores.fill(0);
  document.querySelectorAll(".btn-group").forEach(group => {
    group.querySelectorAll(".score-btn").forEach((btn, idx) => {
      btn.classList.toggle("selected", idx === 0);
    });
  });
  updateSummary();
}

function showError() {
  const banner = document.getElementById("error-banner");
  banner.classList.remove("hidden");
  setTimeout(() => banner.classList.add("hidden"), 5000);
}

function prependHistoryRow(row) {
  const tbody = document.getElementById("history-body");
  document.getElementById("history-empty").classList.add("hidden");
  const tr = document.createElement("tr");
  const sev = getSeverity(row.total);
  tr.innerHTML = `
    <td>${row.timestamp}</td>
    <td>${row.total}</td>
    <td><span class="badge ${sev.cls}">${row.severity}</span></td>
  `;
  tbody.prepend(tr);
}

async function saveAssessment() {
  const total = scores.reduce((a, b) => a + b, 0);
  const { label: severity } = getSeverity(total);
  try {
    const res = await fetch("/api/assessments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scores: [...scores], total, severity }),
    });
    if (!res.ok) throw new Error("Server error");
    const now = new Date();
    const timestamp = now.toLocaleString("fr-FR");
    prependHistoryRow({ timestamp, total, severity });
    resetForm();
  } catch {
    showError();
  }
}

async function loadHistory() {
  try {
    const res = await fetch("/api/assessments");
    if (!res.ok) return;
    const rows = await res.json();
    const tbody = document.getElementById("history-body");
    if (rows.length === 0) {
      document.getElementById("history-empty").classList.remove("hidden");
      return;
    }
    rows.forEach(row => {
      const sev = getSeverity(row.total);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${row.timestamp}</td>
        <td>${row.total}</td>
        <td><span class="badge ${sev.cls}">${row.severity}</span></td>
      `;
      tbody.appendChild(tr);
    });
  } catch {
    // History load failure is non-fatal — silently skip
  }
}

// History toggle
document.getElementById("history-toggle").addEventListener("click", () => {
  const panel = document.getElementById("history-panel");
  const arrow = document.getElementById("toggle-arrow");
  const isHidden = panel.classList.toggle("hidden");
  arrow.textContent = isHidden ? "▼" : "▲";
});

// Save button
document.getElementById("save-btn").addEventListener("click", saveAssessment);

// Init
buildCriteria();
updateSummary();
loadHistory();
```

- [ ] **Step 2: Commit**

```bash
git add cushman/static/app.js
git commit -m "feat(cushman): add JS scoring logic, live updates, and API integration"
```

---

## Task 7: Manual end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run all automated tests**

```bash
cd cushman && python -m pytest tests/ -v
```

Expected: `10 passed`

- [ ] **Step 2: Start the server**

```bash
python -m cushman.app
```

Expected: `Running on http://127.0.0.1:5000`

- [ ] **Step 3: Verify scoring on desktop**

Open `http://localhost:5000` in a browser.
- All 10 criteria visible with buttons 0–7 (last criterion 0–4)
- All buttons start at 0 (highlighted)
- Tap a few buttons — total updates live
- Set all criteria to max (7×9 + 4 = 67) — badge reads "Sevrage sévère" in red
- Set total to 10 — badge reads "Sevrage modéré" in orange
- Set total to 5 — badge reads "Sevrage léger" in green

- [ ] **Step 4: Save an assessment**

Click "Enregistrer".
- All criteria reset to 0
- History toggle button appears
- Click toggle — new row visible in history table

- [ ] **Step 5: Verify persistence**

Reload `http://localhost:5000`.
- History panel (when expanded) shows the previously saved assessment.

- [ ] **Step 6: Verify mobile layout**

Open browser DevTools → toggle device toolbar → set to 375×667 (iPhone SE).
- Buttons are large enough to tap
- Layout is not broken

- [ ] **Step 7: Verify error handling**

Stop the Flask server (Ctrl+C), reload the page, and click "Enregistrer".
Expected: red error banner "Erreur de connexion — score non enregistré" appears and disappears after 5 seconds.

- [ ] **Step 8: Final commit**

```bash
cd cushman
git add .
git commit -m "feat(cushman): complete Score de Cushman app — CIWA-Ar calculator with SQLite persistence"
```
