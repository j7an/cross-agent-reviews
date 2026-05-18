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


def test_input_with_mode_and_profile_tokens(workspace):
    result = run(["--input", "docs/specs/gamma-design.md fast patch"], cwd=workspace)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["slug"] == "gamma"
    assert payload["artifact_type"] == "spec"
    assert payload["mode"] == "fast"
    assert payload["review_profile"] == "patch"


def test_input_with_flag_alias_forms(workspace):
    result = run(
        ["--input", "docs/specs/gamma-design.md --mode=fast --review-profile greenfield"],
        cwd=workspace,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "fast"
    assert payload["review_profile"] == "greenfield"


def test_input_without_tokens_omits_mode_profile(workspace):
    result = run(["--input", "docs/specs/gamma-design.md"], cwd=workspace)
    payload = json.loads(result.stdout)
    assert "mode" not in payload
    assert "review_profile" not in payload


def test_duplicate_mode_tokens_rejected(workspace):
    result = run(["--input", "docs/specs/gamma-design.md fast thorough"], cwd=workspace)
    assert result.returncode == 1
    assert "mode" in result.stderr.lower()


def test_duplicate_profile_tokens_rejected(workspace):
    result = run(["--input", "docs/specs/gamma-design.md patch feature"], cwd=workspace)
    assert result.returncode == 1
    assert "profile" in result.stderr.lower()


def test_two_path_like_tokens_rejected(workspace):
    result = run(["--input", "docs/specs/a-design.md docs/specs/b-design.md"], cwd=workspace)
    assert result.returncode == 1


def test_unknown_extra_token_rejected(workspace):
    result = run(["--input", "docs/specs/gamma-design.md wobble"], cwd=workspace)
    assert result.returncode == 1


def test_reserved_token_without_path_rejected(workspace):
    result = run(["--input", "fast"], cwd=workspace)
    assert result.returncode == 1
    assert "path" in result.stderr.lower() or "slug" in result.stderr.lower()


def test_reserved_word_as_filename_substring_is_a_path(workspace):
    result = run(["--input", "docs/specs/fast-path-design.md"], cwd=workspace)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["slug"] == "fast-path"
    assert "mode" not in payload


def test_dotslash_disambiguates_reserved_word_as_path(workspace):
    # An artifact literally named `fast` is reachable via an unambiguous path
    # form (`./fast` contains `/`, so `_looks_like_path` routes it as a path),
    # whereas the bare token `fast` is always the mode token.
    result = run(["--input", "./fast"], cwd=workspace)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["slug"] == "fast"
    assert "mode" not in payload


def test_input_slug_target_with_mode_token(workspace):
    # A bare slug (not a path, not a reserved word) should be accepted as the
    # target even when mode/profile tokens are present. Use "delta" as a new-
    # slug name not present in the workspace fixture.
    result = run(["--input", "delta fast"], cwd=workspace)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["slug"] == "delta"
    assert payload["mode"] == "fast"


def test_input_empty_alias_value_rejected(workspace):
    # --mode= with an empty value should be rejected with a clear diagnostic.
    result = run(["--input", "docs/specs/gamma-design.md --mode="], cwd=workspace)
    assert result.returncode == 1
    assert "non-empty" in result.stderr
