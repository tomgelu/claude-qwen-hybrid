"""
A command-line tool to compute statistics for CSV files.

Usage:
    python csv_stats.py --input input.csv --output output.md
"""

import csv
import sys
import argparse
import math
from typing import List, Dict, Union, Optional


def calculate_statistics(data: List[str]) -> Dict[str, Union[float, int]]:
    """
    Calculate statistics for a column of data.
    
    Args:
        data: List of string values from a CSV column
        
    Returns:
        Dictionary with statistics: count, mean, median, stddev, null_count
    """
    # Filter out null/empty values
    numeric_values = []
    null_count = 0
    
    for value in data:
        if value.strip() == "" or value.lower() in ("null", "none", "na", "n/a"):
            null_count += 1
        else:
            try:
                numeric_values.append(float(value))
            except ValueError:
                # If value can't be converted to float, treat as null
                null_count += 1
    
    count = len(numeric_values)
    
    # Calculate mean
    mean = sum(numeric_values) / count if count > 0 else 0.0
    
    # Calculate median
    if count == 0:
        median = 0.0
    else:
        sorted_values = sorted(numeric_values)
        n = len(sorted_values)
        if n % 2 == 0:
            median = (sorted_values[n//2 - 1] + sorted_values[n//2]) / 2
        else:
            median = sorted_values[n//2]
    
    # Calculate standard deviation
    if count <= 1:
        stddev = 0.0
    else:
        variance = sum((x - mean) ** 2 for x in numeric_values) / (count - 1)
        stddev = math.sqrt(variance) if variance >= 0 else 0.0
    
    return {
        "count": count,
        "mean": mean,
        "median": median,
        "stddev": stddev,
        "null_count": null_count
    }


def read_csv_file(filepath: str) -> Dict[str, List[str]]:
    """
    Read a CSV file and return a dictionary with column names as keys and lists of values as values.
    
    Args:
        filepath: Path to the CSV file
        
    Returns:
        Dictionary with column names as keys and lists of string values as values
    """
    data = {}
    headers = []
    
    with open(filepath, 'r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        
        # Read headers
        headers = next(reader)
        
        # Initialize empty lists for each column
        for header in headers:
            data[header] = []
        
        # Read data rows
        for row in reader:
            for i, value in enumerate(row):
                if i < len(headers):
                    data[headers[i]].append(value)
    
    return data


def generate_markdown_table(stats: Dict[str, Dict[str, Union[float, int]]]) -> str:
    """
    Generate a Markdown table from the statistics.
    
    Args:
        stats: Dictionary with column names as keys and statistics as values
        
    Returns:
        String containing the Markdown table
    """
    # Header row
    table = "| Column | Count | Mean | Median | StdDev | Null Count |\n"
    
    # Separator row
    table += "| --- | --- | --- | --- | --- | --- |\n"
    
    # Data rows
    for column, column_stats in sorted(stats.items()):
        table += f"| {column} | {column_stats['count']} | {column_stats['mean']:.6f} | {column_stats['median']:.6f} | {column_stats['stddev']:.6f} | {column_stats['null_count']} |\n"
    
    return table


def main():
    """
    Main function to parse arguments and execute the statistics calculation.
    """
    parser = argparse.ArgumentParser(description='Calculate statistics for CSV file columns')
    parser.add_argument('--input', required=True, help='Input CSV file path')
    parser.add_argument('--output', required=True, help='Output Markdown file path')
    
    args = parser.parse_args()
    
    try:
        # Read the CSV file
        data = read_csv_file(args.input)
        
        # Calculate statistics for each column
        column_stats = {}
        for column, values in data.items():
            column_stats[column] = calculate_statistics(values)
        
        # Generate Markdown table
        markdown_table = generate_markdown_table(column_stats)
        
        # Write to output file
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(markdown_table)
        
        print(f"Statistics successfully written to {args.output}")
        
    except FileNotFoundError:
        print(f"Error: Input file '{args.input}' not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
