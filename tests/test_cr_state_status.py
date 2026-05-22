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


def _seed(tmp_path, completed, current_stage, final_status=None, round_3c_final_status=None):
    """Write a state.json under slug 'foo' with the given completed_rounds and
    current_stage, plus a round file per completed stage. If final_status is
    given, round-3b.json carries it. If round_3c_final_status is given,
    round-3c.json carries it along with a passing result."""
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
        if stage == "3c" and round_3c_final_status is not None:
            round_obj["result"] = "passed"
            round_obj["final_status"] = round_3c_final_status
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
        final_status="READY_FOR_IMPLEMENTATION",
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "Terminal:  READY_FOR_IMPLEMENTATION  (via round 3b - zero accepted)" in result.stdout
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


def test_status_via_3b_terminal_with_cpv_is_integrity_error(tmp_path):
    """A via_3b terminal whose round-3b.json has final_status==CORRECTED_PENDING_VERIFICATION
    must report STATE_INTEGRITY_ERROR — the artifact was corrected but never
    verified, so the terminal state is inconsistent."""
    ws = _seed(
        tmp_path,
        ["1a", "1b", "2a", "2b", "3a", "3b"],
        "ready_for_implementation",
        final_status="CORRECTED_PENDING_VERIFICATION",
    )
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


def test_status_clean_3a_terminal_missing_earlier_round_file_no_terminal_summary(tmp_path):
    """The terminal summary must be suppressed when ANY completed round file
    is missing, not only the last. A clean_3a terminal with round-1a.json
    absent but round-3a.json present must report the earliest pending
    import, not READY_FOR_IMPLEMENTATION — matching the read/router path,
    which flags any completed-but-missing stage as a pending import."""
    ws = _seed(tmp_path, ["1a", "1b", "2a", "2b", "3a"], "ready_for_implementation")
    (ws / ".cross-agent-reviews/foo/spec/round-1a.json").unlink()
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "READY_FOR_IMPLEMENTATION" not in result.stdout
    assert "round-1a.json pending import" in result.stdout


def test_status_via_3b_terminal_missing_earlier_round_file_no_terminal_summary(tmp_path):
    """Same guard for a via_3b terminal: an earlier missing completed file
    (round-2a.json) suppresses the final_status summary even though
    round-3b.json is present locally."""
    ws = _seed(
        tmp_path,
        ["1a", "1b", "2a", "2b", "3a", "3b"],
        "ready_for_implementation",
        final_status="READY_FOR_IMPLEMENTATION",
    )
    (ws / ".cross-agent-reviews/foo/spec/round-2a.json").unlink()
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "READY_FOR_IMPLEMENTATION" not in result.stdout
    assert "round-2a.json pending import" in result.stdout


def test_status_via_3c_terminal(tmp_path):
    ws = _seed(
        tmp_path,
        ["1a", "1b", "2a", "2b", "3a", "3b", "3c"],
        "ready_for_implementation",
        round_3c_final_status="CORRECTED_AND_READY",
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    # "3c " (:<3 pad) + "  completed" → "3c   completed" in the timeline row
    assert "3c   completed" in result.stdout
    assert "Terminal:  CORRECTED_AND_READY  (via round 3c" in result.stdout


def test_status_3c_pending(tmp_path):
    ws = _seed(tmp_path, ["1a", "1b", "2a", "2b", "3a", "3b"], "round_3c_pending")
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "3c" in result.stdout
    assert "PENDING  (final verification)" in result.stdout
    assert "Final verification:  PENDING" in result.stdout


def test_status_3c_failed(tmp_path):
    ws = _seed(tmp_path, ["1a", "1b", "2a", "2b", "3a", "3b"], "round_3c_pending")
    attempt = {
        "attempt_number": 1,
        "emitted_at": "2026-05-07T11:00:00Z",
        "verifications": [
            {"finding_id": "F-001", "status": "not_resolved"},
        ],
        "regression_findings": [],
    }
    spec_dir = ws / ".cross-agent-reviews/foo/spec"
    (spec_dir / "round-3c-attempt-001.json").write_text(json.dumps(attempt) + "\n")
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "3c" in result.stdout
    assert "FAILED" in result.stdout
    assert "Final verification:  FAILED" in result.stdout


def test_status_via_3b_skips_3c(tmp_path):
    ws = _seed(
        tmp_path,
        ["1a", "1b", "2a", "2b", "3a", "3b"],
        "ready_for_implementation",
        final_status="READY_FOR_IMPLEMENTATION",
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "skipped (3b accepted zero findings)" in result.stdout


def test_status_shows_mode_and_profile(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    slug_dir = tmp_path / ".cross-agent-reviews" / "foo"
    (slug_dir / "spec").mkdir(parents=True)
    state = {
        "schema_version": 1,
        "slug": "foo",
        "spec": {
            "path": "docs/specs/foo-design.md",
            "content_hash": "sha256:" + "0" * 64,
            "current_stage": "round_1a_pending",
            "completed_rounds": [],
            "started_at": "2026-05-17T10:00:00Z",
            "last_updated_at": "2026-05-17T10:00:00Z",
            "mode": "fast",
            "review_profile": "patch",
        },
    }
    (slug_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    result = run(["--slug", "foo"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "fast" in result.stdout
    assert "patch" in result.stdout


def test_status_legacy_mode_profile_defaults(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    slug_dir = tmp_path / ".cross-agent-reviews" / "foo"
    (slug_dir / "spec").mkdir(parents=True)
    state = {
        "schema_version": 1,
        "slug": "foo",
        "spec": {
            "path": "docs/specs/foo-design.md",
            "content_hash": "sha256:" + "0" * 64,
            "current_stage": "round_1a_pending",
            "completed_rounds": [],
            "started_at": "2026-05-17T10:00:00Z",
            "last_updated_at": "2026-05-17T10:00:00Z",
        },
    }
    (slug_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    result = run(["--slug", "foo"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "thorough (default)" in result.stdout
    assert "legacy" in result.stdout.lower()


def test_status_marks_auto_settled_round(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    slug_dir = tmp_path / ".cross-agent-reviews" / "foo"
    spec_dir = slug_dir / "spec"
    spec_dir.mkdir(parents=True)
    state = {
        "schema_version": 1,
        "slug": "foo",
        "spec": {
            "path": "docs/specs/foo-design.md",
            "content_hash": "sha256:" + "0" * 64,
            "current_stage": "round_2a_pending",
            "completed_rounds": ["1a", "1b"],
            "started_at": "2026-05-17T10:00:00Z",
            "last_updated_at": "2026-05-17T10:05:00Z",
            "mode": "fast",
        },
    }
    (slug_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    (spec_dir / "round-1a.json").write_text(
        json.dumps({"emitted_at": "2026-05-17T10:00:00Z"}) + "\n"
    )
    (spec_dir / "round-1b.json").write_text(
        json.dumps(
            {
                "emitted_at": "2026-05-17T10:05:00Z",
                "auto_settled": {
                    "trigger": "clean_audit_zero_findings",
                    "source_stage": "1a",
                    "source_round_hash": "sha256:" + "a" * 64,
                    "reason": "auto",
                },
            }
        )
        + "\n"
    )
    result = run(["--slug", "foo"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "auto-settled" in result.stdout
    assert "clean 1a" in result.stdout


# ---------------------------------------------------------------------------
# Task 10 — route-line rendering for fast-mode blocks
# ---------------------------------------------------------------------------


def _seed_route_workspace(
    tmp_path,
    *,
    mode,
    review_profile,
    current_stage,
    completed_rounds,
    round_1a=None,
    round_1b=None,
):
    """Seed a workspace with state.json + the supplied round envelopes under
    slug 'foo'. Used by the route-line tests below."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    slug_dir = tmp_path / ".cross-agent-reviews" / "foo"
    spec_dir = slug_dir / "spec"
    spec_dir.mkdir(parents=True)
    block = {
        "path": "docs/specs/foo-design.md",
        "content_hash": "sha256:" + "0" * 64,
        "current_stage": current_stage,
        "completed_rounds": completed_rounds,
        "started_at": "2026-05-17T10:00:00Z",
        "last_updated_at": "2026-05-17T10:05:00Z",
    }
    if mode is not None:
        block["mode"] = mode
    if review_profile is not None:
        block["review_profile"] = review_profile
    state = {"schema_version": 1, "slug": "foo", "spec": block}
    (slug_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    if round_1a is not None:
        (spec_dir / "round-1a.json").write_text(json.dumps(round_1a) + "\n")
    if round_1b is not None:
        (spec_dir / "round-1b.json").write_text(json.dumps(round_1b) + "\n")
    return tmp_path


def _narrow_round_1a():
    return {
        "stage": "1a",
        "emitted_at": "2026-05-17T10:00:00Z",
        "slice_plan": [
            {"agent_id": 1, "is_fixed": False},
            {"agent_id": 3, "is_fixed": False},
            {"agent_id": 5, "is_fixed": False},
        ],
    }


def _narrow_round_1b():
    return {
        "stage": "1b",
        "emitted_at": "2026-05-17T10:05:00Z",
        "accepted_findings": [{"id": "R1-1-001"}, {"id": "R1-3-001"}],
        "adjudications": [
            {
                "finding_id": "R1-1-001",
                "verdict": "accept",
                "fix_criterion": "fix it",
                "verification_target": "target",
            },
            {
                "finding_id": "R1-3-001",
                "verdict": "accept",
                "fix_criterion": "fix it",
                "verification_target": "target",
            },
        ],
        "changelog": [
            {"finding_id": "R1-1-001", "additional_affected_slices": []},
            {"finding_id": "R1-3-001", "additional_affected_slices": []},
        ],
        "finding_lineage": [],
    }


def test_status_renders_narrow_route_line_for_fast_mode_block(tmp_path):
    ws = _seed_route_workspace(
        tmp_path,
        mode="fast",
        review_profile="patch",
        current_stage="round_2a_pending",
        completed_rounds=["1a", "1b"],
        round_1a=_narrow_round_1a(),
        round_1b=_narrow_round_1b(),
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "(narrow: slices 1, 3, 5; mandatory: 5)" in result.stdout


def test_status_narrow_route_line_includes_cross_artifact_mandatory_slice(tmp_path):
    """When a cross-artifact slice (is_fixed=True) is in the plan it is
    mandatory just like the global-coherence slice. Status must name BOTH
    in the `mandatory:` annotation, otherwise an operator cannot tell that
    the cross-artifact slice was included by necessity rather than by
    impact selection."""
    r1a = {
        "stage": "1a",
        "emitted_at": "2026-05-17T10:00:00Z",
        "slice_plan": [
            {"agent_id": 1, "is_fixed": False},
            {"agent_id": 3, "is_fixed": False},
            {"agent_id": 5, "is_fixed": False},
            {"agent_id": 6, "is_fixed": True},
        ],
    }
    ws = _seed_route_workspace(
        tmp_path,
        mode="fast",
        review_profile="patch",
        current_stage="round_2a_pending",
        completed_rounds=["1a", "1b"],
        round_1a=r1a,
        round_1b=_narrow_round_1b(),
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "(narrow: slices 1, 3, 5, 6; mandatory: 5, 6)" in result.stdout


def test_status_renders_broad_route_line_with_fallback_reason(tmp_path):
    """fast/patch with fix_criterion missing on the only accepted finding ->
    F2-1 fallback. Compact one-clause expansion appears."""
    r1a = _narrow_round_1a()
    r1b = {
        "stage": "1b",
        "emitted_at": "2026-05-17T10:05:00Z",
        "accepted_findings": [{"id": "R1-1-001"}],
        "adjudications": [
            {
                "finding_id": "R1-1-001",
                "verdict": "accept",
                # fix_criterion missing
                "verification_target": "target",
            },
        ],
        "changelog": [
            {"finding_id": "R1-1-001", "additional_affected_slices": []},
        ],
        "finding_lineage": [],
    }
    ws = _seed_route_workspace(
        tmp_path,
        mode="fast",
        review_profile="patch",
        current_stage="round_2a_pending",
        completed_rounds=["1a", "1b"],
        round_1a=r1a,
        round_1b=r1b,
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "(broad: fallback — F2-1 missing fix_criterion on R1-1-001)" in result.stdout


def test_status_thorough_mode_block_has_no_route_line(tmp_path):
    """T36 byte-identical guarantee: thorough/unset mode blocks must NOT
    have a route line appended."""
    ws = _seed_route_workspace(
        tmp_path,
        mode="thorough",
        review_profile="patch",
        current_stage="round_2a_pending",
        completed_rounds=["1a", "1b"],
        round_1a=_narrow_round_1a(),
        round_1b=_narrow_round_1b(),
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "(narrow:" not in result.stdout
    assert "(broad: fallback" not in result.stdout


def test_status_route_line_only_when_prior_settle_complete(tmp_path):
    """fast/patch but state is at round_1a_pending — no 1b on disk yet, so
    the 2a row gets no route-line suffix."""
    ws = _seed_route_workspace(
        tmp_path,
        mode="fast",
        review_profile="patch",
        current_stage="round_1a_pending",
        completed_rounds=[],
        round_1a=None,
        round_1b=None,
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "(narrow:" not in result.stdout
    assert "(broad: fallback" not in result.stdout


def test_status_legacy_block_has_no_route_line(tmp_path):
    """Legacy block: no mode, no review_profile. Must not render a route
    line even with 1a + 1b on disk."""
    ws = _seed_route_workspace(
        tmp_path,
        mode=None,
        review_profile=None,
        current_stage="round_2a_pending",
        completed_rounds=["1a", "1b"],
        round_1a=_narrow_round_1a(),
        round_1b=_narrow_round_1b(),
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "(narrow:" not in result.stdout
    assert "(broad: fallback" not in result.stdout


def test_status_fast_mode_with_absent_review_profile_renders_f2_4_line(tmp_path):
    """mode == 'fast' but review_profile unset. Status output for the 2a row
    contains the F2-4 compact expansion from the static map."""
    ws = _seed_route_workspace(
        tmp_path,
        mode="fast",
        review_profile=None,
        current_stage="round_2a_pending",
        completed_rounds=["1a", "1b"],
        round_1a=_narrow_round_1a(),
        round_1b=_narrow_round_1b(),
    )
    result = run(["--slug", "foo"], cwd=ws)
    assert result.returncode == 0, result.stderr
    assert "(broad: fallback — F2-4 review_profile unset (legacy))" in result.stdout


# --- profile/mode suggestion rendering (issue #35) ---


def _write_state(tmp_path, *, review_profile=None, suggestion_evidence=None):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    slug_dir = tmp_path / ".cross-agent-reviews/foo"
    (slug_dir / "spec").mkdir(parents=True)
    block = {
        "path": "docs/specs/foo-design.md",
        "content_hash": "sha256:" + "0" * 64,
        "current_stage": "round_1a_pending",
        "completed_rounds": [],
        "started_at": "2026-05-21T10:00:00Z",
        "last_updated_at": "2026-05-21T10:00:00Z",
    }
    if review_profile is not None:
        block["review_profile"] = review_profile
    if suggestion_evidence is not None:
        block["suggested_review_profile"] = suggestion_evidence["suggested_review_profile"]
        block["suggested_mode"] = suggestion_evidence["suggested_mode"]
        block["suggestion_evidence"] = suggestion_evidence
    state = {"schema_version": 1, "slug": "foo", "spec": block}
    (slug_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return tmp_path


def _evidence(profile="greenfield", mode="thorough", rule="R-INSUFFICIENT-EVIDENCE"):
    return {
        "ruleset_version": 1,
        "artifact_type": "spec",
        "artifact_content_hash": "sha256:" + "0" * 64,
        "resolution": "insufficient_evidence",
        "suggested_review_profile": profile,
        "suggested_mode": mode,
        "fast_eligible": mode == "fast",
        "fired_rules": [],
        "resolution_reason": {"rule_id": rule, "selected_profile": profile},
        "signals": {"referenced_file_paths_count": 0},
    }


def test_status_shows_suggestion_line(tmp_path):
    ws = _write_state(tmp_path, suggestion_evidence=_evidence())
    out = run(["--slug", "foo"], cwd=ws).stdout
    assert "Suggested:" in out
    assert "profile=greenfield" in out


def test_status_flags_divergence_from_locked(tmp_path):
    ws = _write_state(tmp_path, review_profile="patch", suggestion_evidence=_evidence())
    out = run(["--slug", "foo"], cwd=ws).stdout
    assert "diverges from locked" in out
    assert "routing follows locked" in out


def test_status_legacy_block_has_no_suggestion_line(tmp_path):
    ws = _write_state(tmp_path)  # no suggestion fields
    out = run(["--slug", "foo"], cwd=ws).stdout
    assert "Suggested:" not in out
