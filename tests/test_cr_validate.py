"""Tests for cr_validate.py CLI (full round envelopes)."""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers" / "cr_validate.py"


def run(args, stdin=None):
    # Same env-passthrough pattern as Task 3.1's run(): see "Subprocess
    # coverage" in Cross-cutting conventions for why `{**os.environ, ...}`
    # is required for pytest-cov to instrument the subprocess. PATH is
    # inherited from the parent (no override) so host-installed tools
    # remain reachable.
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )


def test_round_1a_audit_valid(fixtures_dir):
    payload = (fixtures_dir / "schema_positive/round_1a_audit.json").read_text()
    result = run(["--kind", "audit"], stdin=payload)
    assert result.returncode == 0


def test_round_1b_settle_valid(fixtures_dir):
    payload = (fixtures_dir / "schema_positive/round_1b_settle.json").read_text()
    result = run(["--kind", "settle"], stdin=payload)
    assert result.returncode == 0


def test_round_audit_wrong_round_for_stage(fixtures_dir):
    payload = (fixtures_dir / "schema_negative/round_audit_wrong_round_for_stage.json").read_text()
    result = run(["--kind", "audit"], stdin=payload)
    assert result.returncode == 1


def test_round_3b_missing_final_status(fixtures_dir):
    payload = (fixtures_dir / "schema_negative/round_3b_missing_final_status.json").read_text()
    result = run(["--kind", "settle"], stdin=payload)
    assert result.returncode == 1
    assert "final_status" in result.stderr


def test_kind_required():
    result = run([], stdin="{}")
    assert result.returncode != 0


def test_state_kind(fixtures_dir):
    payload = (fixtures_dir / "schema_positive/state_spec_only.json").read_text()
    result = run(["--kind", "state"], stdin=payload)
    assert result.returncode == 0
