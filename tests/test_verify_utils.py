from __future__ import annotations

from yo.verify import parse_pytest_summary


def test_parse_pytest_summary_extracts_counts_and_missing_modules() -> None:
    sample_output = """
============================= test session starts ==============================
platform darwin -- Python 3.13.3, pytest-8.4.2
collected 3 items

sample/test_module.py F..

=================================== FAILURES ===================================
________________________________ test_example _________________________________

    def test_example():
>       import missing_lib
E       ModuleNotFoundError: No module named 'missing_lib'

=========================== short test summary info ============================
FAILED sample/test_module.py::test_example - ModuleNotFoundError: No module named 'missing_lib'
======================== 1 failed, 2 passed in 5.00s ===========================
"""

    metrics = parse_pytest_summary(sample_output)
    assert metrics["tests_total"] == 3
    assert metrics["tests_passed"] == 2
    assert metrics["tests_failed"] == 1
    assert metrics["duration_seconds"] == 5.0
    assert metrics["missing_modules"] == ["missing_lib"]
