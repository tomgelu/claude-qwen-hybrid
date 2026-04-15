"""
Test suite for csv_stats.py using pytest and tmp_path fixture.
"""

import csv
import pytest
from pathlib import Path
import subprocess
import sys

# Path to the script under test
SCRIPT_PATH = "csv_stats.py"


def test_normal_data(tmp_path):
    """Test with multiple numeric columns and normal data."""
    # Create a temporary CSV file
    input_file = tmp_path / "input.csv"
    output_file = tmp_path / "output.md"
    
    # Write sample data
    data = [
        ["A", "B", "C"],
        ["1", "2.5", "3"],
        ["2", "3.5", "4"],
        ["3", "4.5", "5"],
        ["4", "5.5", "6"]
    ]
    
    with open(input_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(data)
    
    # Run the script
    result = subprocess.run([
        sys.executable, SCRIPT_PATH, 
        "--input", str(input_file), 
        "--output", str(output_file)
    ], capture_output=True, text=True)
    
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Verify output file was created
    assert output_file.exists(), "Output file was not created"
    
    # Verify content
    content = output_file.read_text()
    assert "| Column | Count | Mean | Median | StdDev | NullCount |" in content
    assert "| A | 5 | 2.5 | 3.0 | 1.118 | 0 |" in content
    assert "| B | 5 | 4.0 | 4.5 | 1.118 | 0 |" in content
    assert "| C | 5 | 4.5 | 5.0 | 1.118 | 0 |" in content


def test_empty_column(tmp_path):
    """Test with one column containing empty strings (not nulls)."""
    input_file = tmp_path / "input.csv"
    output_file = tmp_path / "output.md"
    
    # Write sample data with empty string in column B
    data = [
        ["A", "B", "C"],
        ["1", "", "3"],
        ["2", "", "4"],
        ["3", "", "5"],
        ["4", "", "6"]
    ]
    
    with open(input_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(data)
    
    # Run the script
    result = subprocess.run([
        sys.executable, SCRIPT_PATH, 
        "--input", str(input_file), 
        "--output", str(output_file)
    ], capture_output=True, text=True)
    
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Verify output
    content = output_file.read_text()
    assert "| A | 5 | 2.5 | 3.0 | 1.118 | 0 |" in content
    assert "| B | 5 | 0.0 | 0.0 | 0.0 | 0 |" in content  # Empty strings are treated as 0
    assert "| C | 5 | 4.5 | 5.0 | 1.118 | 0 |" in content


def test_all_null_column(tmp_path):
    """Test with a column containing only null values (empty or missing)."""
    input_file = tmp_path / "input.csv"
    output_file = tmp_path / "output.md"
    
    # Write sample data with empty strings in column B (treated as null)
    data = [
        ["A", "B", "C"],
        ["1", "", "3"],
        ["2", "", "4"],
        ["", "", ""],
        ["4", "", "6"]
    ]
    
    with open(input_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(data)
    
    # Run the script
    result = subprocess.run([
        sys.executable, SCRIPT_PATH, 
        "--input", str(input_file), 
        "--output", str(output_file)
    ], capture_output=True, text=True)
    
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Verify output
    content = output_file.read_text()
    assert "| A | 4 | 2.0 | 1.5 | 1.291 | 1 |" in content  # One null in A
    assert "| B | 0 | 0.0 | 0.0 | 0.0 | 4 |" in content  # All nulls in B
    assert "| C | 4 | 4.0 | 3.5 | 1.291 | 1 |" in content  # One null in C


def test_single_row(tmp_path):
    """Test with a single row of data (edge case)."""
    input_file = tmp_path / "input.csv"
    output_file = tmp_path / "output.md"
    
    # Write single row
    data = [
        ["A", "B", "C"],
        ["1", "2.5", "3"]
    ]
    
    with open(input_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(data)
    
    # Run the script
    result = subprocess.run([
        sys.executable, SCRIPT_PATH, 
        "--input", str(input_file), 
        "--output", str(output_file)
    ], capture_output=True, text=True)
    
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    # Verify output
    content = output_file.read_text()
    assert "| A | 1 | 1.0 | 1.0 | 0.0 | 0 |" in content
    assert "| B | 1 | 2.5 | 2.5 | 0.0 | 0 |" in content
    assert "| C | 1 | 3.0 | 3.0 | 0.0 | 0 |" in content
"""