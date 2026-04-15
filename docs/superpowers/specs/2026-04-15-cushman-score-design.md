# Score de Cushman (CIWA-Ar) — Design Spec

**Date:** 2026-04-15  
**Stack:** Plain HTML/CSS/JS + Python Flask + SQLite  
**Target users:** Nurses and doctors (bedside, mobile + desktop)

---

## Overview

A responsive single-page web app for evaluating alcohol withdrawal severity using the CIWA-Ar scale (Score de Cushman). The clinician scores each of the 10 criteria via large tap-friendly buttons; the total and severity level update live. Completed assessments are saved to a local SQLite database via a Flask API and displayed in a collapsible history panel.

---

## File Structure

```
cushman/
├── app.py              # Flask app — serves index.html + REST API
├── db.py               # SQLite setup and query helpers
├── cushman.db          # SQLite database (auto-created on first run)
├── static/
│   ├── index.html      # Single-page calculator + history panel
│   ├── style.css       # Responsive, mobile-first styles
│   └── app.js          # CIWA-Ar scoring logic + API calls
└── requirements.txt    # flask only
```

---

## Backend

### Flask endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve `index.html` |
| `POST` | `/api/assessments` | Save an assessment |
| `GET` | `/api/assessments` | Return last 50 assessments |

### POST /api/assessments — request body

```json
{
  "scores": [2, 1, 0, 3, 1, 0, 0, 1, 2, 1],
  "total": 11,
  "severity": "modéré"
}
```

### SQLite schema (`db.py`)

```sql
CREATE TABLE IF NOT EXISTS assessments (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    scores    TEXT NOT NULL,   -- JSON array of 10 integers
    total     INTEGER NOT NULL,
    severity  TEXT NOT NULL
);
```

---

## Frontend

### CIWA-Ar Criteria

| # | Criterion (FR) | Max |
|---|----------------|-----|
| 1 | Nausée / Vomissements | 7 |
| 2 | Tremblements | 7 |
| 3 | Sueurs paroxystiques | 7 |
| 4 | Anxiété | 7 |
| 5 | Agitation | 7 |
| 6 | Troubles tactiles | 7 |
| 7 | Troubles auditifs | 7 |
| 8 | Troubles visuels | 7 |
| 9 | Céphalées | 7 |
| 10 | Orientation / Conscience | 4 |

**Maximum total: 67**

### Severity thresholds

| Score | Label | Color |
|-------|-------|-------|
| 0–7 | Sevrage léger | Green |
| 8–15 | Sevrage modéré | Orange |
| ≥ 16 | Sevrage sévère | Red |

### UI behaviour

- Each criterion is rendered as a row: label on the left, numbered buttons (0–N) on the right
- Tapping a button selects it (highlighted); tapping again deselects (resets to 0)
- All criteria start at 0 — the assessment is always valid to save
- Total score and severity badge update in real time as buttons are tapped
- "Enregistrer" button posts to `POST /api/assessments`; on success, appends the new row to the history panel and resets all criteria to 0
- If the API call fails, an inline error banner appears ("Erreur de connexion — score non enregistré") without blocking the UI
- History panel is collapsed by default; a toggle button expands it to show a table of past assessments (timestamp, total, severity)
- Empty history shows: "Aucune évaluation enregistrée"

---

## Error Handling

- **API unreachable:** inline error banner in JS, no crash
- **SQLite write error:** `db.py` raises, Flask returns `500` with JSON `{"error": "..."}`, JS displays the banner
- **Empty history:** graceful empty-state message

---

## Testing

Manual end-to-end:
1. Load page — all scores at 0, total = 0, severity = "léger"
2. Adjust criteria — verify live total and severity badge update correctly
3. Click "Enregistrer" — verify row appears in history panel
4. Reload page — verify history persists from SQLite
5. Stop Flask server, click "Enregistrer" — verify error banner appears without crashing
