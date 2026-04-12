"""
TDD tests for bench.py results table formatting.

Covers format_results_table(runs, task) -> str which renders the
benchmark comparison table for 2 or 3 runs.
"""
import pytest
from bench import format_results_table

EMPTY_STATS = {
    "qwen_in": 0, "qwen_out": 0, "tool_bytes": 0,
    "claude_in": 0, "claude_out": 0,
    "steps_completed": 0, "steps_failed": 0, "steps_total": 0,
    "tests_passed": 0, "tests_failed": 0,
}


def make_stats(**kwargs):
    return {**EMPTY_STATS, **kwargs}


# ── Column count ───────────────────────────────────────────────────────────────

def test_two_runs_produce_two_data_columns():
    runs = [("A (no RTK)", make_stats()), ("B (RTK)", make_stats())]
    table = format_results_table(runs, "test task")
    # Header row should contain both labels
    assert "A (no RTK)" in table
    assert "B (RTK)" in table


def test_three_runs_produce_three_data_columns():
    runs = [
        ("A (no RTK)", make_stats()),
        ("B (RTK)", make_stats()),
        ("C (phases)", make_stats()),
    ]
    table = format_results_table(runs, "test task")
    assert "A (no RTK)" in table
    assert "B (RTK)" in table
    assert "C (phases)" in table


# ── Row content ────────────────────────────────────────────────────────────────

def test_table_contains_token_metrics():
    runs = [("A", make_stats(qwen_in=1000)), ("B", make_stats(qwen_in=800))]
    table = format_results_table(runs, "test task")
    assert "Qwen input tokens" in table
    assert "1,000" in table
    assert "800" in table


def test_table_contains_quality_metrics():
    runs = [
        ("A", make_stats(steps_completed=3, tests_passed=6)),
        ("B", make_stats(steps_completed=3, tests_passed=5)),
    ]
    table = format_results_table(runs, "test task")
    assert "Steps completed" in table
    assert "Tests passed" in table


def test_table_shows_claude_tokens_for_phases_run():
    runs = [
        ("A (no phases)", make_stats(claude_in=0)),
        ("B (phases)",    make_stats(claude_in=4500)),
    ]
    table = format_results_table(runs, "test task")
    assert "Claude input tokens" in table
    assert "4,500" in table


# ── Change indicators ──────────────────────────────────────────────────────────

def test_table_shows_decrease_indicator_when_second_run_is_lower():
    runs = [("A", make_stats(qwen_in=1000)), ("B", make_stats(qwen_in=500))]
    table = format_results_table(runs, "test task")
    assert "▼" in table


def test_table_shows_increase_indicator_when_second_run_is_higher():
    runs = [("A", make_stats(qwen_in=500)), ("B", make_stats(qwen_in=1000))]
    table = format_results_table(runs, "test task")
    assert "▲" in table


def test_table_task_name_is_truncated_to_fit():
    long_task = "x" * 200
    runs = [("A", make_stats()), ("B", make_stats())]
    table = format_results_table(runs, long_task)
    # Table should not be wider than ~70 chars per line
    for line in table.splitlines():
        assert len(line) <= 120, f"Line too wide: {len(line)}: {line!r}"
