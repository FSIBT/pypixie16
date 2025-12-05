"""
Usage:
    python run_tests.py all              # Run all tests
    python run_tests.py fast             # Run fast tests only
    python run_tests.py validation       # Run validation tests only
    python run_tests.py hardware         # Run hardware manager tests
    python run_tests.py integration      # Run integration tests
    python run_tests.py coverage         # Run with coverage report
    python run_tests.py parallel         # Run tests in parallel
    python run_tests.py specific <test>  # Run specific test
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd: list, description: str):
    print(f"\n{'=' * 70}")
    print(f"  {description}")
    print(f"{'=' * 70}\n")
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print(f"\n✓ {description} completed successfully\n")
    else:
        print(f"\n✗ {description} failed with code {result.returncode}\n")
    
    return result.returncode


def run_all_tests():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py", "-v"],
        "Running All Tests"
    )


def run_fast_tests():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py", "-v", "-m", "not slow"],
        "Running Fast Tests Only"
    )


def run_validation_tests():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py::TestParameterValidation", "-v"],
        "Running Parameter Validation Tests"
    )


def run_hardware_tests():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py::TestHardwareManager", "-v"],
        "Running Hardware Manager Tests"
    )


def run_integration_tests():
    return run_command(
        [
            "pytest",
            "test_pixie_scope_integration.py::TestParameterControlsIntegration",
            "test_pixie_scope_integration.py::TestSystemIntegration",
            "-v"
        ],
        "Running Integration Tests"
    )


def run_with_coverage():
    result = run_command(
        [
            "pytest",
            "test_pixie_scope_integration.py",
            "-v",
            "--cov=pixie16.ui.scope",
            "--cov-report=html",
            "--cov-report=term-missing"
        ],
        "Running Tests with Coverage Analysis"
    )
    
    if result == 0:
        print("Coverage report generated: htmlcov/index.html")
    
    return result


def run_parallel_tests():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py", "-v", "-n", "auto"],
        "Running Tests in Parallel"
    )


def run_specific_test(test_name: str):
    return run_command(
        ["pytest", f"test_pixie_scope_integration.py::{test_name}", "-v"],
        f"Running Specific Test: {test_name}"
    )


def run_performance_tests():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py::TestPerformance", "-v"],
        "Running Performance Tests"
    )


def run_error_handling_tests():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py::TestErrorHandling", "-v"],
        "Running Error Handling Tests"
    )


def run_hardware_specs_tests():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py::TestHardwareSpecifications", "-v"],
        "Running Hardware Specifications Tests"
    )


def run_quick_check():
    return run_command(
        [
            "pytest",
            "test_pixie_scope_integration.py::TestParameterValidation::test_trigger_threshold_validation",
            "test_pixie_scope_integration.py::TestHardwareManager::test_dummy_mode_initialization",
            "test_pixie_scope_integration.py::TestSystemIntegration::test_complete_system_initialization",
            "-v"
        ],
        "Running Quick Sanity Check"
    )


def list_all_tests():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py", "--collect-only", "-q"],
        "Listing All Available Tests"
    )


def run_with_debug():
    return run_command(
        ["pytest", "test_pixie_scope_integration.py", "-vv", "-s", "--log-cli-level=DEBUG"],
        "Running Tests with Debug Output"
    )


def main():
    parser = argparse.ArgumentParser(
        description="PIXIE-16 Scope Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py all                    # Run all tests
  python run_tests.py fast                   # Skip slow tests
  python run_tests.py validation             # Run validation tests only
  python run_tests.py coverage               # Run with coverage
  python run_tests.py specific TestName      # Run specific test
  python run_tests.py quick                  # Quick sanity check
  python run_tests.py list                   # List all tests
        """
    )
    
    parser.add_argument(
        "command",
        choices=[
            "all", "fast", "validation", "hardware", "integration",
            "coverage", "parallel", "specific", "performance",
            "error", "specs", "quick", "list", "debug"
        ],
        help="Test command to run"
    )
    
    parser.add_argument(
        "test_name",
        nargs="?",
        help="Specific test name (for 'specific' command)"
    )
    
    args = parser.parse_args()
    
    # Check if test file exists
    test_file = Path("test_pixie_scope_integration.py")
    if not test_file.exists():
        print(f"Error: Test file '{test_file}' not found!")
        print(f"Current directory: {Path.cwd()}")
        return 1
    
    # Route to appropriate function
    commands = {
        "all": run_all_tests,
        "fast": run_fast_tests,
        "validation": run_validation_tests,
        "hardware": run_hardware_tests,
        "integration": run_integration_tests,
        "coverage": run_with_coverage,
        "parallel": run_parallel_tests,
        "performance": run_performance_tests,
        "error": run_error_handling_tests,
        "specs": run_hardware_specs_tests,
        "quick": run_quick_check,
        "list": list_all_tests,
        "debug": run_with_debug,
    }
    
    if args.command == "specific":
        if not args.test_name:
            print("Error: Please provide a test name for 'specific' command")
            print("Example: python run_tests.py specific TestParameterValidation")
            return 1
        return run_specific_test(args.test_name)
    else:
        return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())