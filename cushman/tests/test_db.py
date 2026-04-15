import json
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
