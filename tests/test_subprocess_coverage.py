"""Regression checks for subprocess coverage instrumentation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_python_subprocesses_start_coverage_when_pytest_cov_is_active(request) -> None:
    """pytest-cov runs must propagate coverage startup config to child Python."""
    if not request.config.pluginmanager.hasplugin("_cov"):
        pytest.skip("requires pytest-cov")

    import coverage

    if coverage.Coverage.current() is None:
        pytest.skip("requires an active coverage run")

    probe = (
        "import coverage\n"
        "current = coverage.Coverage.current()\n"
        "print('coverage-started' if current is not None else 'coverage-missing')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "coverage-started"
