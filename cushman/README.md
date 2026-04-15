# Cushman — CIWA-Ar Score Calculator

A bedside web tool for nurses and doctors to evaluate alcohol withdrawal severity
using the CIWA-Ar (Clinical Institute Withdrawal Assessment for Alcohol) scale.

## What it is

Single-page Flask app that:
- Guides clinicians through 10 CIWA-Ar criteria with live scoring
- Classifies severity: léger (&lt;8), modéré (8–15), sévère (≥16)
- Persists assessments in SQLite and displays the last 50 in a history panel

## Running with Docker (recommended)

```bash
docker compose up -d cushman
# Access at http://<server-ip>:5000
```

## Running locally

```bash
pip install -r cushman/requirements.txt
python3 -m cushman.app
# Access at http://localhost:5000
```

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Serves the single-page app |
| POST | `/api/assessments` | Save an assessment |
| GET | `/api/assessments` | List last 50 assessments |

### POST /api/assessments — request body

```json
{
  "scores": [0, 1, 2, 0, 1, 0, 0, 0, 1, 0],
  "total": 5,
  "severity": "léger"
}
```

`scores` is an array of 10 integers (one per CIWA-Ar criterion, in order):

1. Nausée/Vomissements
2. Tremblements
3. Sueurs paroxystiques
4. Anxiété
5. Agitation
6. Troubles tactiles
7. Troubles auditifs
8. Troubles visuels
9. Céphalées
10. Orientation/Conscience

## Running tests

```bash
python3 -m pytest cushman/tests/ -v
```
