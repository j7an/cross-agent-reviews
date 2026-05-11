"""Tests for cr_validate_finding.py CLI."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers" / "cr_validate_finding.py"


def run(args, stdin=None):
    # The helper runs in script mode, so `_helpers/` is auto-added to
    # `sys.path[0]` and `from _cr_lib import …` resolves with no extra
    # PYTHONPATH munging. We still set PYTHONPATH=REPO_ROOT so the
    # repo-root `sitecustomize.py` runs in the subprocess and triggers
    # `coverage.process_startup()` (subprocess-coverage convention). We
    # pass the parent process env through (`{**os.environ, ...}`) so
    # pytest-cov's COV_CORE_* / COVERAGE_PROCESS_START variables propagate
    # to the subprocess; otherwise the script's main() body would not be
    # measured under the --cov-fail-under=85 gate (see "Subprocess
    # coverage" in Cross-cutting conventions). PATH is inherited from the
    # parent so host-installed tools (`git`, `bats`) remain reachable;
    # pinning PATH to a fixed list would break on hosts where these
    # binaries live elsewhere (Homebrew on macOS, `uv`-managed
    # environments). The same pattern applies to every CLI test helper in
    # the project (Task 3.2 onwards).
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )


def test_valid_finding_from_stdin(fixtures_dir):
    payload = (fixtures_dir / "schema_positive/finding_minimal.json").read_text()
    result = run([], stdin=payload)
    assert result.returncode == 0


def test_valid_finding_from_file(fixtures_dir, tmp_path):
    src = fixtures_dir / "schema_positive/finding_minimal.json"
    result = run(["--file", str(src)])
    assert result.returncode == 0


def test_invalid_finding_missing_severity(fixtures_dir):
    payload = (fixtures_dir / "schema_negative/finding_missing_severity.json").read_text()
    result = run([], stdin=payload)
    assert result.returncode == 1
    assert "severity" in result.stderr


def test_malformed_json(tmp_path):
    result = run([], stdin="{ not json")
    assert result.returncode == 1
    assert "JSON" in result.stderr or "json" in result.stderr
