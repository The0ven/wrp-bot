#!/usr/bin/env python3
"""
Test runner for WRP Bot calendar approval system
Runs all tests without requiring Discord to be running
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

def run_tests(test_type="all", verbose=False, coverage=False):
    """Run the specified tests"""
    
    # Ensure we're in the right directory
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    # Check if pytest is available
    try:
        import pytest
    except ImportError:
        print("❌ pytest not found!")
        print("Please install test dependencies:")
        print("  pip install -e .[test]")
        print("  or")
        print("  pip install pytest pytest-asyncio pytest-mock pytest-cov")
        return False
    
    # Build pytest command
    cmd = ["python3", "-m", "pytest"]
    
    if test_type == "unit":
        cmd.extend(["tests/test_approval_views.py", "tests/test_views.py"])
    elif test_type == "integration":
        cmd.extend(["tests/test_integration.py"])
    elif test_type == "all":
        cmd.extend(["tests/"])
    else:
        print(f"Unknown test type: {test_type}")
        return False
    
    if verbose:
        cmd.append("-v")
    
    if coverage:
        cmd.extend(["--cov=approval_views", "--cov=views", "--cov-report=html", "--cov-report=term"])
    
    # Add test discovery
    cmd.extend(["-s", "--tb=short"])
    
    print(f"Running tests: {' '.join(cmd)}")
    print("=" * 60)
    
    try:
        result = subprocess.run(cmd, check=True)
        print("=" * 60)
        print("✅ All tests passed!")
        return True
    except subprocess.CalledProcessError as e:
        print("=" * 60)
        print(f"❌ Tests failed with exit code {e.returncode}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Run WRP Bot tests")
    parser.add_argument(
        "--type", 
        choices=["unit", "integration", "all"], 
        default="all",
        help="Type of tests to run"
    )
    parser.add_argument(
        "-v", "--verbose", 
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--coverage", 
        action="store_true",
        help="Generate coverage report"
    )
    
    args = parser.parse_args()
    
    print("🧪 WRP Bot Test Runner")
    print("=" * 60)
    print(f"Test Type: {args.type}")
    print(f"Verbose: {args.verbose}")
    print(f"Coverage: {args.coverage}")
    print()
    
    # Check if test dependencies are installed
    try:
        import pytest
        import pytest_asyncio
        import pytest_mock
    except ImportError as e:
        print("❌ Test dependencies not found!")
        print(f"Missing: {e.name}")
        print("\nTo install test dependencies:")
        print("  pip install -e .[test]")
        print("  or")
        print("  pip install pytest pytest-asyncio pytest-mock pytest-cov")
        print()
        return False
    
    success = run_tests(args.type, args.verbose, args.coverage)
    
    if success:
        print("\n🎉 Test run completed successfully!")
        sys.exit(0)
    else:
        print("\n💥 Test run failed!")
        sys.exit(1)

if __name__ == "__main__":
    main() 