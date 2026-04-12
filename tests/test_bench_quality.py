"""
TDD tests for bench.py quality tracking.

Covers capture_quality(workspace, state) -> dict which is the new
function responsible for extracting step-completion and pytest results.
"""
import os
import textwrap
import tempfile
import pytest

from bench import capture_quality


# ── Step completion counts ─────────────────────────────────────────────────────

def test_capture_quality_counts_completed_steps():
    state = {"completed_steps": [1, 2, 3], "failed_steps": [], "skipped_steps": []}
    result = capture_quality("/tmp/fake", state)
    assert result["steps_completed"] == 3


def test_capture_quality_counts_failed_steps():
    state = {"completed_steps": [1], "failed_steps": [2, 3], "skipped_steps": []}
    result = capture_quality("/tmp/fake", state)
    assert result["steps_failed"] == 2


def test_capture_quality_computes_total_from_completed_and_failed():
    state = {"completed_steps": [1, 2], "failed_steps": [3], "skipped_steps": [4]}
    result = capture_quality("/tmp/fake", state)
    assert result["steps_total"] == 4


# ── Pytest results ─────────────────────────────────────────────────────────────

def test_capture_quality_runs_pytest_and_reports_passing_tests():
    with tempfile.TemporaryDirectory() as ws:
        (open(os.path.join(ws, "test_sample.py"), "w")
         .write(textwrap.dedent("""
             def test_one(): assert 1 + 1 == 2
             def test_two(): assert 'a' in 'abc'
         """)))
        state = {"completed_steps": [], "failed_steps": [], "skipped_steps": []}
        result = capture_quality(ws, state)
        assert result["tests_passed"] == 2
        assert result["tests_failed"] == 0


def test_capture_quality_reports_failing_tests():
    with tempfile.TemporaryDirectory() as ws:
        (open(os.path.join(ws, "test_broken.py"), "w")
         .write(textwrap.dedent("""
             def test_bad(): assert False
             def test_ok(): assert True
         """)))
        state = {"completed_steps": [], "failed_steps": [], "skipped_steps": []}
        result = capture_quality(ws, state)
        assert result["tests_passed"] == 1
        assert result["tests_failed"] == 1


def test_capture_quality_returns_zero_tests_when_no_test_files():
    with tempfile.TemporaryDirectory() as ws:
        state = {"completed_steps": [], "failed_steps": [], "skipped_steps": []}
        result = capture_quality(ws, state)
        assert result["tests_passed"] == 0
        assert result["tests_failed"] == 0
