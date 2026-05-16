"""Tests for cr_state_write.py."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPERS = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers"
SCRIPT = HELPERS / "cr_state_write.py"
INIT_SCRIPT = HELPERS / "cr_state_init.py"


def run(script, args, cwd, stdin=None):
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )


@pytest.fixture
def workspace_with_state(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "tests" / "fixtures" / "artifacts" / "spec.md",
        tmp_path / "docs" / "specs" / "foo-design.md",
    )
    schema_src = REPO_ROOT / "plugin" / "skills" / "cr" / "_shared" / "schema"
    schema_dst = tmp_path / "plugin" / "skills" / "cr" / "_shared" / "schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(schema_src, schema_dst)
    artifact = tmp_path / "docs" / "specs" / "foo-design.md"
    run(
        INIT_SCRIPT,
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=tmp_path,
        stdin="",
    )
    return tmp_path


def write_round(workspace, input_fixture):
    src = REPO_ROOT / "tests" / "fixtures" / "state_write_inputs" / input_fixture
    return run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(src),
        ],
        cwd=workspace,
    )


def test_writes_round_1a_envelope(workspace_with_state):
    result = write_round(workspace_with_state, "round_1a_input.json")
    assert result.returncode == 0, result.stderr
    round_path = workspace_with_state / ".cross-agent-reviews/foo/spec/round-1a.json"
    assert round_path.exists()
    env = json.loads(round_path.read_text())
    assert env["stage"] == "1a"
    assert env["round"] == 1
    assert env["agents"][0]["findings"][0]["id"] == "R1-1-001"


def test_round_1a_stdout_matches_file(workspace_with_state):
    result = write_round(workspace_with_state, "round_1a_input.json")
    file_content = (
        workspace_with_state / ".cross-agent-reviews/foo/spec/round-1a.json"
    ).read_text()
    assert result.stdout == file_content


def test_state_advances_after_1a(workspace_with_state):
    write_round(workspace_with_state, "round_1a_input.json")
    state = json.loads((workspace_with_state / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_1b_pending"
    assert state["spec"]["completed_rounds"] == ["1a"]


def test_settle_round_carries_slice_plan_and_accepted_findings(workspace_with_state):
    write_round(workspace_with_state, "round_1a_input.json")
    result = write_round(workspace_with_state, "round_1b_input.json")
    assert result.returncode == 0, result.stderr
    env = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-1b.json").read_text()
    )
    assert env["stage"] == "1b"
    assert env["accepted_findings"][0]["id"] == "R1-1-001"
    assert env["adjudication_summary"] == {"accepted": 1, "rejected": 0}
    assert len(env["slice_plan"]) == 5  # carried from 1a


def test_1b_accepts_nit_severity_finding(workspace_with_state):
    """Round 1a can emit `nit` findings; Round 1b may adjudicate one as
    accepted. The settle schema no longer gates 1b accepted-finding severity
    (only 3b stays blocker-only), so the writer must build and schema-validate
    a 1b envelope whose `accepted_findings` carries the inherited `nit`
    severity from the paired 1a audit."""
    write_round(workspace_with_state, "round_1a_input_nit.json")
    result = write_round(workspace_with_state, "round_1b_input.json")
    assert result.returncode == 0, result.stderr
    env = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-1b.json").read_text()
    )
    assert env["accepted_findings"][0]["id"] == "R1-1-001"
    assert env["accepted_findings"][0]["severity"] == "nit"


def test_settle_round_refreshes_content_hash_after_artifact_edit(workspace_with_state):
    """A settle round (1b/2b/3b) edits the artifact in place per the round
    procedures. After the round writes, `state.<artifact_type>.content_hash`
    MUST equal the post-edit bytes' hash so a later plan-init under the same
    slug anchors `state.plan.spec_hash_at_start` to the *approved* spec
    rather than the pre-review spec — preventing a false-drift report on
    the very first plan-rounds drift check."""
    write_round(workspace_with_state, "round_1a_input.json")
    artifact = workspace_with_state / "docs/specs/foo-design.md"
    state_path = workspace_with_state / ".cross-agent-reviews/foo/state.json"
    pre_hash = json.loads(state_path.read_text())["spec"]["content_hash"]
    # Simulate the 1b author's edit-in-place by appending bytes to the spec.
    artifact.write_text(artifact.read_text() + "\n<!-- 1b correction -->\n")
    result = write_round(workspace_with_state, "round_1b_input.json")
    assert result.returncode == 0, result.stderr
    state_after = json.loads(state_path.read_text())
    expected_hash = "sha256:" + __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    assert state_after["spec"]["content_hash"] == expected_hash
    assert state_after["spec"]["content_hash"] != pre_hash


def test_2a_verifications_must_match_accepted_count(workspace_with_state):
    write_round(workspace_with_state, "round_1a_input.json")
    write_round(workspace_with_state, "round_1b_input.json")
    result = write_round(workspace_with_state, "round_2a_input.json")
    assert result.returncode == 0, result.stderr


def test_2a_rejects_when_verification_count_off(workspace_with_state, tmp_path):
    write_round(workspace_with_state, "round_1a_input.json")
    write_round(workspace_with_state, "round_1b_input.json")
    bad = json.loads(
        (REPO_ROOT / "tests/fixtures/state_write_inputs/round_2a_input.json").read_text()
    )
    # remove the only verification while accepted_findings still has 1 entry
    bad["agents"][0]["round_1_verifications"] = []
    bad_path = tmp_path / "bad_2a.json"
    bad_path.write_text(json.dumps(bad))
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(bad_path),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 1
    assert "verifications" in result.stderr.lower() or "round_1_verifications" in result.stderr


def test_2b_accepts_revisit_changelog_with_round_1_finding_id(workspace_with_state, tmp_path):
    """A 2b author may revisit an unresolved Round 1 verification by adding a
    changelog entry whose finding_id is the original `R1-*` id (per 2b §2).
    The writer must accept these ids by sourcing them from the paired 2a's
    round_1_verifications, even though they are not in the 2a NEW findings
    list. Adjudications still must reference 2a NEW findings only."""
    write_round(workspace_with_state, "round_1a_input.json")
    write_round(workspace_with_state, "round_1b_input.json")
    write_round(workspace_with_state, "round_2a_input.json")

    # The shared 2a fixture marks R1-1-001 verifications as `resolved`. A
    # legitimate 2b revisit only happens when the verification was NOT resolved
    # — and the M4 invariant rejects revisits of already-resolved verifications
    # (see test_2b_rejects_revisit_of_resolved_verification). Flip the 2a
    # round_1_verifications status to `not_resolved` for this happy-path test
    # so the revisit is legal.
    artifact_dir = workspace_with_state / ".cross-agent-reviews/foo/spec"
    audit_2a = json.loads((artifact_dir / "round-2a.json").read_text())
    for agent in audit_2a["agents"]:
        for v in agent.get("round_1_verifications", []):
            if v["round_1_finding_id"] == "R1-1-001":
                v["status"] = "not_resolved"
    (artifact_dir / "round-2a.json").write_text(
        json.dumps(audit_2a, indent=2, sort_keys=True) + "\n"
    )

    payload = {
        "stage": "2b",
        "adjudications": [],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R1-1-001",
                "change_made": "Re-tightened §3.2 wording after 2a flagged residual ambiguity.",
            }
        ],
        "self_review": [
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "",
            }
        ],
    }
    payload_path = tmp_path / "2b_revisit.json"
    payload_path.write_text(json.dumps(payload))
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(payload_path),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 0, result.stderr
    env = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-2b.json").read_text()
    )
    assert env["changelog"][0]["finding_id"] == "R1-1-001"


def _walk_to_2b_with_unresolved_verification(workspace, fid="R1-1-001"):
    """Walk a workspace through 1a/1b/2a and flip the named verification's
    status to `not_resolved` so the M4 revisit-pairing tests can exercise
    legitimate revisit scenarios. Returns the per-test artifact directory."""
    write_round(workspace, "round_1a_input.json")
    write_round(workspace, "round_1b_input.json")
    write_round(workspace, "round_2a_input.json")
    artifact_dir = workspace / ".cross-agent-reviews/foo/spec"
    audit_2a = json.loads((artifact_dir / "round-2a.json").read_text())
    for agent in audit_2a["agents"]:
        for v in agent.get("round_1_verifications", []):
            if v["round_1_finding_id"] == fid:
                v["status"] = "not_resolved"
    (artifact_dir / "round-2a.json").write_text(
        json.dumps(audit_2a, indent=2, sort_keys=True) + "\n"
    )
    return artifact_dir


def _run_2b_write(workspace, payload, tmp_path, name):
    payload_path = tmp_path / name
    payload_path.write_text(json.dumps(payload))
    return run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(payload_path),
        ],
        cwd=workspace,
    )


def test_2b_rejects_revisit_changelog_without_paired_self_review(workspace_with_state, tmp_path):
    """M4 invariant 1: every 2b revisit changelog entry (one whose finding_id
    is sourced from the paired 2a's round_1_verifications) MUST have a paired
    self_review entry. Without this, an author can submit a revisit edit
    without holding it to the same fix-before-emit standard, breaking the
    audit-trail contract that the accepted-finding pairing rule already
    enforces for 2a NEW findings."""
    _walk_to_2b_with_unresolved_verification(workspace_with_state)
    payload = {
        "stage": "2b",
        "adjudications": [],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R1-1-001",
                "change_made": "Re-tightened §3.2 wording after 2a flagged residual ambiguity.",
            }
        ],
        "self_review": [],  # ← orphan changelog entry; no paired self_review
    }
    result = _run_2b_write(workspace_with_state, payload, tmp_path, "2b_orphan_changelog.json")
    assert result.returncode == 1
    assert "R1-1-001" in result.stderr
    assert "self_review" in result.stderr.lower() or "self review" in result.stderr.lower()


def test_2b_rejects_revisit_self_review_without_paired_changelog(workspace_with_state, tmp_path):
    """M4 invariant 1, reverse direction: every 2b revisit self_review entry
    MUST have a paired changelog entry. A self_review with no matching edit
    is a self-attestation about a change that was never made."""
    _walk_to_2b_with_unresolved_verification(workspace_with_state)
    payload = {
        "stage": "2b",
        "adjudications": [],
        "rejected_findings": [],
        "changelog": [],
        "self_review": [
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "",
            }
        ],
    }
    result = _run_2b_write(workspace_with_state, payload, tmp_path, "2b_orphan_self_review.json")
    assert result.returncode == 1
    assert "R1-1-001" in result.stderr
    assert "changelog" in result.stderr.lower()


def test_2b_rejects_revisit_of_resolved_verification(workspace_with_state, tmp_path):
    """M4 invariant 2: a 2b revisit changelog entry whose paired 2a
    round_1_verification has status='resolved' must be rejected — that
    correction was already verified resolved by the 2a reviewer, so a
    revisit makes no sense and would corrupt the audit trail."""
    write_round(workspace_with_state, "round_1a_input.json")
    write_round(workspace_with_state, "round_1b_input.json")
    write_round(workspace_with_state, "round_2a_input.json")
    # The shared 2a fixture already has R1-1-001 with status=resolved; no
    # mutation needed for this test — that is precisely the scenario the
    # invariant guards against.
    payload = {
        "stage": "2b",
        "adjudications": [],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R1-1-001",
                "change_made": "Pointless revisit of an already-resolved verification.",
            }
        ],
        "self_review": [
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "",
            }
        ],
    }
    result = _run_2b_write(workspace_with_state, payload, tmp_path, "2b_revisit_resolved.json")
    assert result.returncode == 1
    assert "R1-1-001" in result.stderr
    assert "resolved" in result.stderr.lower()


def test_3b_final_status_ready_when_no_blockers(workspace_with_state, tmp_path):
    """Walk to round_3b_pending, then write a 3b settle and assert final_status."""
    # Walk: 1a → 1b → 2a; then forge 2b/3a/3b state directly so the test
    # stays focused on `final_status` derivation rather than re-exercising
    # every cross-round invariant (the integration tests in Phase 12 cover
    # the full walk).
    write_round(workspace_with_state, "round_1a_input.json")
    write_round(workspace_with_state, "round_1b_input.json")
    write_round(workspace_with_state, "round_2a_input.json")

    artifact_dir = workspace_with_state / ".cross-agent-reviews/foo/spec"
    state_path = workspace_with_state / ".cross-agent-reviews/foo/state.json"

    # Write a minimal 2b settle (no findings carried forward) and a 3a audit
    # with all agents `ship_ready`. Both files are produced by hand so we can
    # advance state without inventing additional fixture-driven CLI inputs.
    settle_2b = json.loads((artifact_dir / "round-1b.json").read_text())
    settle_2b.update(
        {
            "round": 2,
            "stage": "2b",
            "adjudication_summary": {"accepted": 0, "rejected": 0},
            "adjudications": [],
            "accepted_findings": [],
            "rejected_findings": [],
            "changelog": [],
            "self_review": [],
        }
    )
    (artifact_dir / "round-2b.json").write_text(
        json.dumps(settle_2b, indent=2, sort_keys=True) + "\n"
    )

    audit_3a = json.loads((artifact_dir / "round-1a.json").read_text())
    audit_3a.update({"round": 3, "stage": "3a"})
    for agent in audit_3a["agents"]:
        agent["status"] = "ship_ready"
        agent["findings"] = []
        agent["round_1_verifications"] = []
    (artifact_dir / "round-3a.json").write_text(
        json.dumps(audit_3a, indent=2, sort_keys=True) + "\n"
    )

    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "round_3b_pending"
    state["spec"]["completed_rounds"] = ["1a", "1b", "2a", "2b", "3a"]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    # 3b input with empty adjudications drives final_status = READY_FOR_IMPLEMENTATION.
    src = REPO_ROOT / "tests/fixtures/state_write_inputs/round_3b_input.json"
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(src),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 0, result.stderr

    env = json.loads((artifact_dir / "round-3b.json").read_text())
    assert env["stage"] == "3b"
    assert env["final_status"] == "READY_FOR_IMPLEMENTATION"
    assert env["accepted_findings"] == []


def test_round_id_assignment_pattern(workspace_with_state):
    write_round(workspace_with_state, "round_1a_input.json")
    env = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-1a.json").read_text()
    )
    finding_id = env["agents"][0]["findings"][0]["id"]
    assert finding_id.startswith("R1-1-")
    assert finding_id.endswith("001")


def test_invalid_input_rejected_by_schema(workspace_with_state, tmp_path):
    # Build an input with a malformed finding (missing severity)
    bad = {
        "stage": "1a",
        "slice_plan": [
            {"agent_id": 1, "concern": "x", "slice_definition": "y", "is_fixed": False},
            {"agent_id": 2, "concern": "x", "slice_definition": "y", "is_fixed": False},
            {"agent_id": 3, "concern": "x", "slice_definition": "y", "is_fixed": False},
            {"agent_id": 4, "concern": "x", "slice_definition": "y", "is_fixed": False},
            {"agent_id": 5, "concern": "x", "slice_definition": "y", "is_fixed": False},
        ],
        "agents": [
            {
                "agent_id": 1,
                "concern": "x",
                "slice_definition": "y",
                "status": "findings_found",
                "findings": [
                    {
                        "location": "L",
                        "finding": "F",
                        "why_it_matters": "W",
                        "suggested_direction": "S",
                    }
                ],
            },
            {
                "agent_id": 2,
                "concern": "x",
                "slice_definition": "y",
                "status": "clean",
                "findings": [],
            },
            {
                "agent_id": 3,
                "concern": "x",
                "slice_definition": "y",
                "status": "clean",
                "findings": [],
            },
            {
                "agent_id": 4,
                "concern": "x",
                "slice_definition": "y",
                "status": "clean",
                "findings": [],
            },
            {
                "agent_id": 5,
                "concern": "x",
                "slice_definition": "y",
                "status": "clean",
                "findings": [],
            },
        ],
    }
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad))
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(bad_path),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 1


def test_settle_rejects_accepted_finding_without_changelog(workspace_with_state, tmp_path):
    """Schema-valid settle envelopes that accept a finding without recording
    the corresponding edit (changelog entry) must be refused. This is a
    cross-array invariant that schema validation cannot express on its own."""
    write_round(workspace_with_state, "round_1a_input.json")
    bad = json.loads(
        (REPO_ROOT / "tests/fixtures/state_write_inputs/round_1b_input.json").read_text()
    )
    bad["changelog"] = []  # accept R1-1-001 but record no changelog
    bad_path = tmp_path / "bad_1b.json"
    bad_path.write_text(json.dumps(bad))
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(bad_path),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 1
    assert "changelog" in result.stderr.lower()


def test_settle_rejects_accepted_finding_without_self_review(workspace_with_state, tmp_path):
    """Same invariant for self_review: every accepted finding must have a
    self_review entry; otherwise downstream rounds have no evidence to
    verify against."""
    write_round(workspace_with_state, "round_1a_input.json")
    bad = json.loads(
        (REPO_ROOT / "tests/fixtures/state_write_inputs/round_1b_input.json").read_text()
    )
    bad["self_review"] = []
    bad_path = tmp_path / "bad_1b.json"
    bad_path.write_text(json.dumps(bad))
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(bad_path),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 1
    assert "self_review" in result.stderr.lower()


def test_artifact_path_mismatch_rejected(workspace_with_state):
    """The script must refuse to emit an envelope whose --artifact-path
    diverges from what state.json captured at init time. Without this guard,
    a local round emitted with the wrong path is only caught on the
    destination host during `cr_state_read.py --paste`, which is too late."""
    src = REPO_ROOT / "tests" / "fixtures" / "state_write_inputs" / "round_1a_input.json"
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/wrong-path.md",
            "--input",
            str(src),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 1
    assert "artifact-path" in result.stderr.lower() or "does not match" in result.stderr.lower()


def test_rejects_state_with_schema_violation_invalid_stage(workspace_with_state):
    """A state.json whose `current_stage` is not in the schema's enum (e.g.,
    hand-edited or corrupted to `round_99_pending`) must be rejected on read
    by the writer. Without this guard the writer would mutate
    schema-violating state and persist invalid bytes back, propagating the
    corruption forward. The error must include the JSON pointer so the
    operator can locate the offending field without re-running."""
    state_path = workspace_with_state / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "round_99_pending"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    src = REPO_ROOT / "tests" / "fixtures" / "state_write_inputs" / "round_1a_input.json"
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(src),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 1
    assert "schema violation" in result.stderr.lower()
    assert "/spec/current_stage" in result.stderr
    # The round file must NOT have been written.
    assert not (workspace_with_state / ".cross-agent-reviews/foo/spec/round-1a.json").exists()


def test_rejects_state_with_schema_violation_missing_required_field(workspace_with_state):
    """A state.json missing a required top-level field (e.g., `slug`) must be
    rejected before the writer mutates it. The both-block invariant only
    catches one specific cross-block case; broader schema violations need
    schema validation."""
    state_path = workspace_with_state / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    del state["slug"]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    src = REPO_ROOT / "tests" / "fixtures" / "state_write_inputs" / "round_1a_input.json"
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(src),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 1
    assert "schema violation" in result.stderr.lower()
    # The round file must NOT have been written.
    assert not (workspace_with_state / ".cross-agent-reviews/foo/spec/round-1a.json").exists()


def test_rejects_state_with_both_blocks_missing_spec_anchor(workspace_with_state, tmp_path):
    """If state.json has both spec and plan blocks, plan.spec_hash_at_start
    MUST be present. Otherwise spec-drift detection silently no-ops. This
    invariant is also enforced in `cr_state_read.py --paste`; the writer
    re-checks it at every round entry so a corrupted local state surfaces
    immediately rather than after the operator has emitted further round
    envelopes."""
    state_path = workspace_with_state / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "ready_for_implementation"
    state["plan"] = {
        "path": "docs/plans/foo-plan.md",
        "content_hash": "sha256:" + "0" * 64,
        "current_stage": "round_1a_pending",
        "completed_rounds": [],
        "started_at": "2026-05-07T11:00:00Z",
        "last_updated_at": "2026-05-07T11:00:00Z",
        # NOTE: deliberately omit spec_hash_at_start
    }
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    src = REPO_ROOT / "tests" / "fixtures" / "state_write_inputs" / "round_1a_input.json"
    result = run(
        SCRIPT,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "plan",
            "--artifact-path",
            "docs/plans/foo-plan.md",
            "--input",
            str(src),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 1
    assert "spec_hash_at_start" in result.stderr
