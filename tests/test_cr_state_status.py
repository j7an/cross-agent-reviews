"""Tests for cr_state_status.py."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers" / "cr_state_status.py"


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


def _seed(tmp_path, completed, current_stage, final_status=None):
    """Write a state.json under slug 'foo' with the given completed_rounds and
    current_stage, plus a round file per completed stage. If final_status is
    given, round-3b.json carries it."""
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
            "current_stage": current_stage,
            "completed_rounds": completed,
            "started_at": "2026-05-07T09:00:00Z",
            "last_updated_at": "2026-05-07T10:00:00Z",
        },
    }
    (slug_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    for stage in completed:
        round_obj = {"stage": stage, "emitted_at": "2026-05-07T10:00:00Z"}
        if stage == "3b" and final_status is not None:
            round_obj["final_status"] = final_status
        (spec_dir / f"round-{stage}.json").write_text(json.dumps(round_obj) + "\n")
    return tmp_path


def test_status_clean_3a_terminal(tmp_path):
    ws = _seed(tmp_path, ["1a", "1b", "2a", "2b", "3a"], "ready_for_implementation")
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "skipped (clean 3a)" in result.stdout
    assert "Terminal:" in result.stdout
    assert "READY_FOR_IMPLEMENTATION  (clean 3a - round 3b skipped)" in result.stdout


def test_status_via_3b_terminal(tmp_path):
    ws = _seed(
        tmp_path,
        ["1a", "1b", "2a", "2b", "3a", "3b"],
        "ready_for_implementation",
        final_status="CORRECTED_AND_READY",
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "Terminal:  CORRECTED_AND_READY  (via round 3b)" in result.stdout
    assert "skipped (clean 3a)" not in result.stdout


def test_status_round_3b_pending_has_no_terminal_line(tmp_path):
    ws = _seed(tmp_path, ["1a", "1b", "2a", "2b", "3a"], "round_3b_pending")
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "3b" in result.stdout
    assert "PENDING" in result.stdout
    assert "Terminal:" not in result.stdout
    assert "skipped (clean 3a)" not in result.stdout


def test_status_invalid_terminal_shape_shows_integrity_error(tmp_path):
    ws = _seed(tmp_path, ["1a", "2a", "3a"], "ready_for_implementation")
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "STATE_INTEGRITY_ERROR" in result.stdout
    assert "Terminal:" not in result.stdout


def test_status_clean_3a_terminal_missing_round_file_no_terminal_summary(tmp_path):
    """When a clean_3a terminal's round-3a.json is absent locally, status must
    not print the READY_FOR_IMPLEMENTATION summary — the read/router path
    treats the missing completed-round file as a pending import. Mirrors the
    via_3b branch's existing round-3b.json guard."""
    ws = _seed(tmp_path, ["1a", "1b", "2a", "2b", "3a"], "ready_for_implementation")
    (ws / ".cross-agent-reviews/foo/spec/round-3a.json").unlink()
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "READY_FOR_IMPLEMENTATION" not in result.stdout
    assert "round-3a.json pending import" in result.stdout
