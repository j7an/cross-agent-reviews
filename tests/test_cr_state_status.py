"""Tests for cr_state_status.py."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "cr_state_status.py"


def run(args, cwd, stdin=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )


@pytest.fixture
def workspace_with_one_round(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    slug_dir = tmp_path / ".cross-agent-reviews/foo"
    spec_dir = slug_dir / "spec"
    spec_dir.mkdir(parents=True)
    state = {
        "schema_version": 1,
        "slug": "foo",
        "spec": {
            "path": "docs/specs/foo-design.md",
            "content_hash": "sha256:" + "0" * 64,
            "current_stage": "round_1b_pending",
            "completed_rounds": ["1a"],
            "started_at": "2026-05-07T10:00:00Z",
            "last_updated_at": "2026-05-07T10:30:00Z",
        },
    }
    (slug_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    (spec_dir / "round-1a.json").write_text(
        json.dumps(
            {
                "stage": "1a",
                "round": 1,
                "schema_version": 1,
                "slug": "foo",
                "artifact_type": "spec",
                "artifact_path": "docs/specs/foo-design.md",
                "emitted_at": "2026-05-07T10:30:00Z",
                "slice_plan": [],
                "agents": [],
            }
        )
    )
    return tmp_path


def test_status_lists_slug_and_completed_round(workspace_with_one_round):
    result = run(["--slug", "foo"], cwd=workspace_with_one_round)
    assert result.returncode == 0
    assert "Slug: foo" in result.stdout
    assert "1a" in result.stdout
    assert "completed" in result.stdout
    assert "1b" in result.stdout
    assert "PENDING" in result.stdout


def test_status_no_slug_lists_all(workspace_with_one_round):
    result = run([], cwd=workspace_with_one_round)
    assert result.returncode == 0
    assert "foo" in result.stdout


def test_status_integrity_ok(workspace_with_one_round):
    result = run(["--slug", "foo"], cwd=workspace_with_one_round)
    assert "State integrity:" in result.stdout
    assert "OK" in result.stdout
