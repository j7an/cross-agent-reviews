"""Tests for cr_state_pick_slug.py."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers" / "cr_state_pick_slug.py"


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
def workspace(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _make_slug(
    workspace,
    name,
    *,
    current_stage="round_1b_pending",
    last_updated="2026-05-07T12:00:00Z",
    completed=("1a",),
    with_round_files=True,
):
    slug_dir = workspace / ".cross-agent-reviews" / name
    spec_dir = slug_dir / "spec"
    spec_dir.mkdir(parents=True)
    state = {
        "schema_version": 1,
        "slug": name,
        "spec": {
            "path": f"docs/specs/{name}-design.md",
            "content_hash": "sha256:" + "0" * 64,
            "current_stage": current_stage,
            "completed_rounds": list(completed),
            "started_at": "2026-05-07T10:00:00Z",
            "last_updated_at": last_updated,
        },
    }
    (slug_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    if with_round_files:
        for r in completed:
            (spec_dir / f"round-{r}.json").write_text(
                json.dumps(
                    {
                        "stage": r,
                        "round": int(r[0]),
                        "schema_version": 1,
                        "slug": name,
                        "artifact_type": "spec",
                        "artifact_path": f"docs/specs/{name}-design.md",
                        "emitted_at": last_updated,
                        "slice_plan": [],
                        "agents": [],
                    }
                )
            )


def test_no_active_slugs_asks_for_artifact(workspace):
    result = run([], cwd=workspace)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["action"] == "ask_for_artifact_path"


def test_single_active_slug_returned(workspace):
    _make_slug(workspace, "alpha")
    result = run([], cwd=workspace)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["slug"] == "alpha"
    # The router calls `cr_state_init.py --artifact-type` and `cr_state_read.py
    # --artifact-type` after no-input advance, so the picker MUST emit
    # artifact_type for the single-active case (derived from the latest block
    # in state.json).
    assert payload["artifact_type"] == "spec"


def test_two_active_slugs_default_by_recency(workspace):
    _make_slug(workspace, "alpha", last_updated="2026-05-07T10:00:00Z")
    _make_slug(workspace, "beta", last_updated="2026-05-07T13:00:00Z")
    result = run([], cwd=workspace)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["default"] == "beta"
    assert payload["alternatives"] == ["alpha"]


def test_pending_import_surfaces_first(workspace):
    _make_slug(workspace, "alpha", last_updated="2026-05-07T13:00:00Z")
    _make_slug(
        workspace,
        "beta",
        completed=("1a",),
        with_round_files=False,
        last_updated="2026-05-07T10:00:00Z",
    )
    result = run([], cwd=workspace)
    payload = json.loads(result.stdout)
    assert payload["default"] == "beta"


def test_explicit_path_arg_derives_slug(workspace):
    _make_slug(workspace, "alpha")
    result = run(["--input", "docs/specs/gamma-design.md"], cwd=workspace)
    payload = json.loads(result.stdout)
    assert payload["slug"] == "gamma"
    # When the input is an artifact path, the picker also derives
    # artifact_type so the router can pass it directly to cr_state_init.py
    # without a second prompt (§5.5; required for the spec→plan handoff
    # where state.json exists but the plan block is absent).
    assert payload["artifact_type"] == "spec"


def test_explicit_plan_path_arg_derives_artifact_type(workspace):
    result = run(["--input", "docs/plans/gamma-plan.md"], cwd=workspace)
    payload = json.loads(result.stdout)
    assert payload["slug"] == "gamma"
    assert payload["artifact_type"] == "plan"


def test_explicit_slug_name_arg(workspace):
    _make_slug(workspace, "alpha")
    _make_slug(workspace, "beta")
    result = run(["--input", "alpha"], cwd=workspace)
    payload = json.loads(result.stdout)
    assert payload["slug"] == "alpha"
    # Slug-name match is also the second invocation after disambiguation, so
    # it MUST emit artifact_type when state.json has a block for the slug.
    assert payload["artifact_type"] == "spec"
