"""Every case recorded in the test report also runs as a test."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_test_report as report  # noqa: E402


@pytest.mark.parametrize(
    "case", report.build_cases(), ids=lambda case: f"{case.group}: {case.name}"
)
def test_recorded_case(case, tmp_path):
    assert report.run(case, str(tmp_path), 0)["passed"]
