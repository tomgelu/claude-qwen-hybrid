"""TDD tests for bench.py persistence — _write_bench_results and wall_time_s."""
import os
import sqlite3
import tempfile


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
        try:
            rows = conn.execute("SELECT * FROM bench_runs ORDER BY id").fetchall()
        finally:
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
        try:
            rows = conn.execute("SELECT run_id FROM bench_runs ORDER BY id").fetchall()
        finally:
            conn.close()

        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"
        assert rows[0][0] == "run1", f"Expected 'run1', got {rows[0][0]!r}"
        assert rows[1][0] == "run2", f"Expected 'run2', got {rows[1][0]!r}"
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
