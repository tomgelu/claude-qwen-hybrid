"""TDD tests for bench.py persistence — _write_bench_results and wall_time_s."""
import json
import os
import tempfile
import pytest


def test_run_once_result_includes_wall_time_s():
    """run_once() result dict must contain wall_time_s as a non-negative number."""
    from bench import _average_stats
    import inspect
    src = inspect.getsource(_average_stats)
    assert "wall_time_s" in src, "_average_stats must include wall_time_s in its keys list"


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
