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


def save_assessment(scores: list, total: int, severity: str) -> int:
    con = _connect()
    cur = con.execute(
        "INSERT INTO assessments (scores, total, severity) VALUES (?, ?, ?)",
        (json.dumps(scores), total, severity),
    )
    con.commit()
    row_id = cur.lastrowid
    con.close()
    return row_id


def get_assessments(limit: int = 50) -> list:
    con = _connect()
    cur = con.execute(
        "SELECT id, timestamp, scores, total, severity FROM assessments ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def get_assessment_by_id(id: int) -> dict | None:
    con = _connect()
    cur = con.execute(
        "SELECT id, timestamp, scores, total, severity FROM assessments WHERE id = ?",
        (id,),
    )
    row = cur.fetchone()
    con.close()
    if row is None:
        return None
    row_dict = dict(row)
    row_dict['scores'] = json.loads(row_dict['scores'])
    return row_dict