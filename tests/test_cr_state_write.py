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


@pytest.fixture
def workspace_fast(tmp_path):
    """Like workspace_with_state but the spec block is inited with mode=fast."""
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
        [
            "--artifact-path",
            str(artifact),
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
            "--mode",
            "fast",
        ],
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


def _walk_to_3a_pending(workspace):
    """Walk 1a->1b->2a via the writer, forge a minimal 2b settle file, and set
    state to round_3a_pending so a 3a write can be exercised directly. Mirrors
    the setup in test_3b_final_status_ready_when_no_blockers."""
    write_round(workspace, "round_1a_input.json")
    write_round(workspace, "round_1b_input.json")
    write_round(workspace, "round_2a_input.json")
    artifact_dir = workspace / ".cross-agent-reviews/foo/spec"
    state_path = workspace / ".cross-agent-reviews/foo/state.json"
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
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "round_3a_pending"
    state["spec"]["completed_rounds"] = ["1a", "1b", "2a", "2b"]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def test_3a_clean_terminates_pipeline(workspace_with_state):
    """A clean 3a (every agent ship_ready) routes straight to
    ready_for_implementation with the five-round clean_3a shape; no 3b runs."""
    _walk_to_3a_pending(workspace_with_state)
    result = write_round(workspace_with_state, "round_3a_input.json")
    assert result.returncode == 0, result.stderr
    state = json.loads((workspace_with_state / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "ready_for_implementation"
    assert state["spec"]["completed_rounds"] == ["1a", "1b", "2a", "2b", "3a"]
    assert not (workspace_with_state / ".cross-agent-reviews/foo/spec/round-3b.json").exists()
    # Envelope shape is unchanged: no final_status, no extra keys.
    env = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-3a.json").read_text()
    )
    assert "final_status" not in env
    assert set(env.keys()) == {
        "round",
        "stage",
        "schema_version",
        "slug",
        "artifact_type",
        "artifact_path",
        "emitted_at",
        "slice_plan",
        "agents",
    }


def test_3a_non_clean_advances_to_round_3b(workspace_with_state):
    """Regression guard: a 3a with >=1 blocker_found agent still advances to
    round_3b_pending — the non-clean path is unchanged."""
    _walk_to_3a_pending(workspace_with_state)
    result = write_round(workspace_with_state, "round_3a_input_blocker.json")
    assert result.returncode == 0, result.stderr
    state = json.loads((workspace_with_state / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_3b_pending"
    assert state["spec"]["completed_rounds"] == ["1a", "1b", "2a", "2b", "3a"]


def test_3b_accept_emits_corrected_pending_verification(workspace_with_state):
    # drive 1a..3a with a 3a blocker, then 3b accepting it
    _walk_to_3a_pending(workspace_with_state)
    write_round(workspace_with_state, "round_3a_input_blocker.json")
    result = write_round(workspace_with_state, "round_3b_input_accept.json")
    assert result.returncode == 0, result.stderr
    env = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-3b.json").read_text()
    )
    assert env["final_status"] == "CORRECTED_PENDING_VERIFICATION"
    state = json.loads((workspace_with_state / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_3c_pending"
    assert "3c" not in state["spec"]["completed_rounds"]


def test_3b_zero_accepted_terminates_ready(workspace_with_state):
    _walk_to_3a_pending(workspace_with_state)
    write_round(workspace_with_state, "round_3a_input_blocker.json")
    result = write_round(workspace_with_state, "round_3b_input_adjudicate.json")  # rejects all
    assert result.returncode == 0, result.stderr
    env = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-3b.json").read_text()
    )
    assert env["final_status"] == "READY_FOR_IMPLEMENTATION"
    state = json.loads((workspace_with_state / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "ready_for_implementation"


def _drive_to_3c_pending(workspace):
    write_round(workspace, "round_1a_input.json")
    write_round(workspace, "round_1b_input.json")
    write_round(workspace, "round_2a_input.json")
    write_round(workspace, "round_2b_input.json")
    write_round(workspace, "round_3a_input_blocker.json")
    write_round(workspace, "round_3b_input_accept.json")


def test_3c_pass_terminates_via_3c(workspace_with_state):
    _drive_to_3c_pending(workspace_with_state)
    result = write_round(workspace_with_state, "round_3c_input_pass.json")
    assert result.returncode == 0, result.stderr
    env = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-3c.json").read_text()
    )
    assert env["result"] == "passed"
    assert env["final_status"] == "CORRECTED_AND_READY"
    assert env["attempt_number"] == 1
    assert env["prior_attempts"] == []
    state = json.loads((workspace_with_state / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "ready_for_implementation"
    assert "3c" in state["spec"]["completed_rounds"]
    assert state["spec"]["content_hash"] == env["verified_content_hash"]


def test_3c_fail_writes_attempt_file_and_leaves_state(workspace_with_state):
    _drive_to_3c_pending(workspace_with_state)
    before = json.loads((workspace_with_state / ".cross-agent-reviews/foo/state.json").read_text())
    result = write_round(workspace_with_state, "round_3c_input_fail.json")
    assert result.returncode == 0, result.stderr
    attempt = workspace_with_state / ".cross-agent-reviews/foo/spec/round-3c-attempt-001.json"
    assert attempt.exists()
    env = json.loads(attempt.read_text())
    assert env["result"] == "failed"
    assert "final_status" not in env
    after = json.loads((workspace_with_state / ".cross-agent-reviews/foo/state.json").read_text())
    assert after == before  # failed 3c does not mutate state.json
    assert not (workspace_with_state / ".cross-agent-reviews/foo/spec/round-3c.json").exists()


def test_3c_rerun_guard_blocks_unchanged_artifact(workspace_with_state):
    _drive_to_3c_pending(workspace_with_state)
    write_round(workspace_with_state, "round_3c_input_fail.json")  # attempt 1
    result = write_round(workspace_with_state, "round_3c_input_fail.json")  # no edit
    assert result.returncode == 1
    assert "rerun guard" in result.stderr


def test_3c_missing_verification_rejected(workspace_with_state):
    _drive_to_3c_pending(workspace_with_state)
    # an empty-verifications payload -> 1:1 invariant fails (and minItems)
    bad = workspace_with_state / "bad_3c.json"
    bad.write_text(json.dumps({"stage": "3c", "verifications": [], "regression_findings": []}))
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
            str(bad),
        ],
        cwd=workspace_with_state,
    )
    assert result.returncode == 1
    assert "missing a verification" in result.stderr


def test_3c_attempt_numbering_is_max_based(workspace_with_state):
    """attempt-001 pruned, attempt-002 surviving -> next failed attempt is 003,
    not 002 (max-based, not count-based — count would collide with 002)."""
    _drive_to_3c_pending(workspace_with_state)
    spec_dir = workspace_with_state / ".cross-agent-reviews/foo/spec"
    surviving = {
        "round": 3,
        "stage": "3c",
        "schema_version": 1,
        "slug": "foo",
        "artifact_type": "spec",
        "artifact_path": "docs/specs/foo-design.md",
        "emitted_at": "2026-05-16T11:00:00Z",
        "attempt_number": 2,
        "verified_content_hash": "sha256:" + "b" * 64,
        "verifications": [
            {"round_3a_finding_id": "R3-1-001", "status": "not_resolved", "evidence": "x"}
        ],
        "regression_findings": [],
        "result": "failed",
        "prior_attempts": [],
    }
    (spec_dir / "round-3c-attempt-002.json").write_text(json.dumps(surviving))
    result = write_round(workspace_with_state, "round_3c_input_fail.json")
    assert result.returncode == 0, result.stderr
    assert (spec_dir / "round-3c-attempt-003.json").exists()
    assert (spec_dir / "round-3c-attempt-002.json").exists()  # surviving file untouched


def test_3c_second_fail_records_prior_attempt(workspace_with_state):
    """A second failed attempt summarizes the first in prior_attempts."""
    _drive_to_3c_pending(workspace_with_state)
    spec_dir = workspace_with_state / ".cross-agent-reviews/foo/spec"
    write_round(workspace_with_state, "round_3c_input_fail.json")  # attempt-001
    # operator recovery edit so the rerun guard does not block the rerun
    artifact = workspace_with_state / "docs/specs/foo-design.md"
    artifact.write_text(artifact.read_text() + "\n<!-- recovery edit -->\n")
    result = write_round(workspace_with_state, "round_3c_input_fail.json")  # attempt-002
    assert result.returncode == 0, result.stderr
    env2 = json.loads((spec_dir / "round-3c-attempt-002.json").read_text())
    assert env2["attempt_number"] == 2
    assert len(env2["prior_attempts"]) == 1
    assert env2["prior_attempts"][0]["attempt_number"] == 1
    assert "R3-1-001" in env2["prior_attempts"][0]["not_resolved_finding_ids"]


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


def test_2a_missing_round_1b_exits_clean(workspace_with_state):
    """Writing round 2a when round-1b.json is absent must exit nonzero with a
    clean diagnostic, not crash with a TypeError traceback. Regression for
    issue #17."""
    # Setup: drive the pipeline to round_2a_pending. Assert each setup write
    # succeeds so a setup regression cannot masquerade as the missing-file case.
    r1a = write_round(workspace_with_state, "round_1a_input.json")
    assert r1a.returncode == 0, r1a.stderr
    r1b = write_round(workspace_with_state, "round_1b_input.json")
    assert r1b.returncode == 0, r1b.stderr

    # Remove the on-disk dependency the 2a cross-round check needs. State still
    # legitimately expects 2a next.
    round_1b = workspace_with_state / ".cross-agent-reviews/foo/spec/round-1b.json"
    assert round_1b.exists()
    round_1b.unlink()

    result = write_round(workspace_with_state, "round_2a_input.json")

    assert result.returncode == 1
    assert "round 2a requires round-1b.json" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (workspace_with_state / ".cross-agent-reviews/foo/spec/round-2a.json").exists()


def test_is_clean_helpers_importable():
    """The eligibility helpers exist and classify envelopes correctly."""
    sys.path.insert(0, str(HELPERS))
    try:
        import cr_state_write as w
    finally:
        sys.path.pop(0)
    clean_1a = {"agents": [{"status": "clean", "findings": [], "round_1_verifications": []}]}
    dirty_1a = {
        "agents": [{"status": "findings_found", "findings": [{}], "round_1_verifications": []}]
    }
    assert w._is_clean_1a(clean_1a) is True
    assert w._is_clean_1a(dirty_1a) is False
    clean_2a = {
        "agents": [
            {
                "status": "verified",
                "findings": [],
                "round_1_verifications": [{"status": "resolved"}],
            }
        ]
    }
    unresolved_2a = {
        "agents": [
            {
                "status": "verified",
                "findings": [],
                "round_1_verifications": [{"status": "not_resolved"}],
            }
        ]
    }
    new_finding_2a = {
        "agents": [{"status": "issues_found", "findings": [{}], "round_1_verifications": []}]
    }
    assert w._is_clean_2a(clean_2a) is True
    assert w._is_clean_2a(unresolved_2a) is False
    assert w._is_clean_2a(new_finding_2a) is False


def test_fast_clean_1a_auto_settles_to_1b(workspace_fast):
    result = write_round(workspace_fast, "round_1a_clean_input.json")
    assert result.returncode == 0, result.stderr
    base = workspace_fast / ".cross-agent-reviews/foo/spec"
    assert (base / "round-1a.json").exists()
    assert (base / "round-1b.json").exists()
    state = json.loads((workspace_fast / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_2a_pending"
    assert state["spec"]["completed_rounds"] == ["1a", "1b"]


def test_fast_clean_1a_auto_settled_evidence(workspace_fast):
    from _cr_lib import compute_content_hash

    write_round(workspace_fast, "round_1a_clean_input.json")
    base = workspace_fast / ".cross-agent-reviews/foo/spec"
    settle = json.loads((base / "round-1b.json").read_text())
    assert settle["stage"] == "1b"
    assert settle["adjudication_summary"] == {"accepted": 0, "rejected": 0}
    assert settle["accepted_findings"] == []
    ev = settle["auto_settled"]
    assert ev["trigger"] == "clean_audit_zero_findings"
    assert ev["source_stage"] == "1a"
    assert ev["reason"]
    assert ev["source_round_hash"] == compute_content_hash(base / "round-1a.json")


def test_fast_clean_1a_stdout_is_written_rounds_wrapper(workspace_fast):
    from _cr_lib import canonical_json

    result = write_round(workspace_fast, "round_1a_clean_input.json")
    payload = json.loads(result.stdout)
    assert set(payload) == {"written_rounds"}
    assert [r["stage"] for r in payload["written_rounds"]] == ["1a", "1b"]
    base = workspace_fast / ".cross-agent-reviews/foo/spec"
    assert canonical_json(payload["written_rounds"][0]) == (base / "round-1a.json").read_text()
    assert canonical_json(payload["written_rounds"][1]) == (base / "round-1b.json").read_text()


def test_fast_1a_with_findings_does_not_auto_settle(workspace_fast):
    result = write_round(workspace_fast, "round_1a_input.json")
    assert result.returncode == 0, result.stderr
    base = workspace_fast / ".cross-agent-reviews/foo/spec"
    assert (base / "round-1a.json").exists()
    assert not (base / "round-1b.json").exists()
    state = json.loads((workspace_fast / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_1b_pending"
    assert "written_rounds" not in result.stdout


def test_thorough_clean_1a_does_not_auto_settle(workspace_with_state):
    result = write_round(workspace_with_state, "round_1a_clean_input.json")
    assert result.returncode == 0, result.stderr
    base = workspace_with_state / ".cross-agent-reviews/foo/spec"
    assert not (base / "round-1b.json").exists()
    state = json.loads((workspace_with_state / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_1b_pending"


def test_fast_clean_2a_auto_settles_to_2b(workspace_fast):
    # Clean 1a auto-settles to 1b; state is now round_2a_pending.
    write_round(workspace_fast, "round_1a_clean_input.json")
    result = write_round(workspace_fast, "round_2a_clean_input.json")
    assert result.returncode == 0, result.stderr
    base = workspace_fast / ".cross-agent-reviews/foo/spec"
    assert (base / "round-2a.json").exists()
    assert (base / "round-2b.json").exists()
    state = json.loads((workspace_fast / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_3a_pending"
    assert state["spec"]["completed_rounds"] == ["1a", "1b", "2a", "2b"]


def test_fast_clean_2a_auto_settled_evidence(workspace_fast):
    from _cr_lib import compute_content_hash

    write_round(workspace_fast, "round_1a_clean_input.json")
    write_round(workspace_fast, "round_2a_clean_input.json")
    base = workspace_fast / ".cross-agent-reviews/foo/spec"
    settle = json.loads((base / "round-2b.json").read_text())
    assert settle["stage"] == "2b"
    ev = settle["auto_settled"]
    assert ev["source_stage"] == "2a"
    assert ev["source_round_hash"] == compute_content_hash(base / "round-2a.json")


def test_auto_settle_failure_keeps_manual_settle_boundary(workspace_fast):
    # Pre-create round-1b.json as a non-empty directory so the auto-settle
    # atomic_write of round-1b.json fails with OSError.
    artifact_dir = workspace_fast / ".cross-agent-reviews/foo/spec"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    blocker = artifact_dir / "round-1b.json"
    blocker.mkdir()
    (blocker / "placeholder").write_text("not a round file")

    result = write_round(workspace_fast, "round_1a_clean_input.json")

    # The audit write succeeded; exit 0.
    assert result.returncode == 0, result.stderr
    assert (artifact_dir / "round-1a.json").exists()
    # State stays exactly at the manual-settle boundary.
    state = json.loads((workspace_fast / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_1b_pending"
    assert state["spec"]["completed_rounds"] == ["1a"]
    # Explicit structured failure marker on stderr.
    assert "AUTO_SETTLE_FAILED:" in result.stderr
    # stdout is the single 1a audit envelope (byte-identical to the file).
    assert result.stdout == (artifact_dir / "round-1a.json").read_text()


# ---------------------------------------------------------------------------
# finding_lineage emission on 1b settle (issue #22, Task 5)
#
# Spec §3.3: the writer emits `finding_lineage` only when BOTH `mode == "fast"`
# AND `review_profile is not None` (the "fast / profile-aware" gate). Legacy
# thorough envelopes and fast-without-profile envelopes MUST NOT carry the
# field at all.
# ---------------------------------------------------------------------------


def _setup_fast_workspace(tmp_path, *, mode: str | None = "fast", review_profile: str | None):
    """Initialise a workspace whose spec block carries an explicit mode and/or
    review_profile combination. Returns the workspace root path.

    Mirrors the `workspace_fast` fixture but exposes both knobs so a single
    helper covers the four matrix cells the lineage gate exercises:
      - mode=fast,     review_profile=patch       → emit
      - mode=fast,     review_profile=None        → do not emit
      - mode=thorough, review_profile=anything    → do not emit
      - mode=None,     review_profile=anything    → do not emit
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
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
    init_args = [
        "--artifact-path",
        str(artifact),
        "--artifact-type",
        "spec",
        "--no-gitignore-prompt",
    ]
    if mode is not None:
        init_args += ["--mode", mode]
    if review_profile is not None:
        init_args += ["--review-profile", review_profile]
    run(INIT_SCRIPT, init_args, cwd=tmp_path, stdin="")
    return tmp_path


def _lineage_1a_agents(findings_by_agent: dict[int, list[dict]] | None = None) -> list[dict]:
    """Build the `agents` list for a 5-slice 1a audit input.

    `findings_by_agent` keys are agent_ids (1..5); values are finding dicts
    (without `id` — the writer assigns it). Agents not in the dict report
    `clean` with an empty findings list. Default = all clean.
    """
    findings_by_agent = findings_by_agent or {}
    concerns = {
        1: ("Data model & schemas", "§3-§5"),
        2: ("Error handling & edge cases", "§6"),
        3: ("Acceptance criteria & testability", "§7-§8"),
        4: ("Cross-section consistency", "all"),
        5: ("Global coherence", "all"),
    }
    out: list[dict] = []
    for aid in range(1, 6):
        concern, slice_def = concerns[aid]
        findings = findings_by_agent.get(aid, [])
        out.append(
            {
                "agent_id": aid,
                "concern": concern,
                "slice_definition": slice_def,
                "status": "findings_found" if findings else "clean",
                "findings": findings,
            }
        )
    return out


def _lineage_1a_slice_plan() -> list[dict]:
    return [
        {
            "agent_id": 1,
            "concern": "Data model & schemas",
            "slice_definition": "§3-§5",
            "is_fixed": False,
        },
        {
            "agent_id": 2,
            "concern": "Error handling & edge cases",
            "slice_definition": "§6",
            "is_fixed": False,
        },
        {
            "agent_id": 3,
            "concern": "Acceptance criteria & testability",
            "slice_definition": "§7-§8",
            "is_fixed": False,
        },
        {
            "agent_id": 4,
            "concern": "Cross-section consistency",
            "slice_definition": "all",
            "is_fixed": False,
        },
        {
            "agent_id": 5,
            "concern": "Global coherence",
            "slice_definition": "all",
            "is_fixed": False,
        },
    ]


def _lineage_finding(
    location: str = "§3.2 line 47",
    severity: str = "blocker",
    finding: str = "Field foo is undefined.",
    why: str = "Implementer cannot decide its type.",
    suggested: str = "Define foo in §3.2.",
) -> dict:
    return {
        "location": location,
        "severity": severity,
        "finding": finding,
        "why_it_matters": why,
        "suggested_direction": suggested,
    }


def _write_input(tmp_path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def _run_writer_with_input(workspace, input_path: Path):
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
            str(input_path),
        ],
        cwd=workspace,
    )


def _drive_to_1b_pending(workspace, tmp_path, *, findings_by_agent):
    """Write a 1a audit round with the supplied findings; return when state
    is at round_1b_pending. Used by every lineage test below."""
    input_1a = {
        "stage": "1a",
        "slice_plan": _lineage_1a_slice_plan(),
        "agents": _lineage_1a_agents(findings_by_agent),
    }
    input_path = _write_input(tmp_path, "1a_lineage_input.json", input_1a)
    result = _run_writer_with_input(workspace, input_path)
    assert result.returncode == 0, result.stderr


def test_1b_emits_finding_lineage_when_author_fields_complete(tmp_path):
    workspace = _setup_fast_workspace(tmp_path / "wf", review_profile="patch")
    _drive_to_1b_pending(
        workspace,
        tmp_path,
        findings_by_agent={1: [_lineage_finding(location="L1")]},
    )
    payload_1b = {
        "stage": "1b",
        "adjudications": [
            {
                "finding_id": "R1-1-001",
                "verdict": "accept",
                "reasoning": "fix",
                "fix_criterion": "c",
                "verification_target": "t",
            }
        ],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R1-1-001",
                "change_made": "edit",
                "additional_affected_slices": [3],
            }
        ],
        "self_review": [
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "ok",
            }
        ],
    }
    input_path = _write_input(tmp_path, "1b_complete.json", payload_1b)
    result = _run_writer_with_input(workspace, input_path)
    assert result.returncode == 0, result.stderr
    settled = json.loads((workspace / ".cross-agent-reviews/foo/spec/round-1b.json").read_text())
    assert settled["finding_lineage"] == [
        {
            "lineage_id": "L-1b-R1-1-001",
            "original_finding_id": "R1-1-001",
            "originating_stage": "1a",
            "originating_agent_id": 1,
            "originating_slice": "Data model & schemas",
            "affected_location": "L1",
            "affected_slices": [1, 3],
            "fix_criterion": "c",
            "verification_target": "t",
            "prior_lineage_id": None,
            "latest_verification": None,
        }
    ]


def test_1b_emits_empty_finding_lineage_when_no_accepted_findings(tmp_path):
    workspace = _setup_fast_workspace(tmp_path / "wf", review_profile="patch")
    # Clean 1a — fast/patch auto-settles to a 1b with zero accepted findings.
    _drive_to_1b_pending(workspace, tmp_path, findings_by_agent={})
    settled = json.loads((workspace / ".cross-agent-reviews/foo/spec/round-1b.json").read_text())
    assert settled["finding_lineage"] == []


def test_1b_emits_lineage_for_accept_only_skips_rejects(tmp_path):
    workspace = _setup_fast_workspace(tmp_path / "wf", review_profile="patch")
    _drive_to_1b_pending(
        workspace,
        tmp_path,
        findings_by_agent={
            1: [
                _lineage_finding(location="L-accept"),
                _lineage_finding(
                    location="L-reject",
                    finding="Different concern",
                    suggested="Other direction",
                ),
            ]
        },
    )
    payload_1b = {
        "stage": "1b",
        "adjudications": [
            {
                "finding_id": "R1-1-001",
                "verdict": "accept",
                "reasoning": "fix",
                "fix_criterion": "c",
                "verification_target": "t",
            },
            {
                "finding_id": "R1-1-002",
                "verdict": "reject",
                "reasoning": "false positive",
            },
        ],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R1-1-001",
                "change_made": "edit",
                "additional_affected_slices": [],
            }
        ],
        "self_review": [
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "ok",
            }
        ],
    }
    input_path = _write_input(tmp_path, "1b_mixed.json", payload_1b)
    result = _run_writer_with_input(workspace, input_path)
    assert result.returncode == 0, result.stderr
    settled = json.loads((workspace / ".cross-agent-reviews/foo/spec/round-1b.json").read_text())
    assert len(settled["finding_lineage"]) == 1
    assert settled["finding_lineage"][0]["original_finding_id"] == "R1-1-001"


def test_1b_omits_lineage_row_and_warns_on_missing_author_fields(tmp_path):
    workspace = _setup_fast_workspace(tmp_path / "wf", review_profile="patch")
    _drive_to_1b_pending(
        workspace,
        tmp_path,
        findings_by_agent={1: [_lineage_finding(location="L1")]},
    )
    payload_1b = {
        "stage": "1b",
        "adjudications": [
            {
                "finding_id": "R1-1-001",
                "verdict": "accept",
                "reasoning": "fix",
                # fix_criterion intentionally absent
                "verification_target": "t",
            }
        ],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R1-1-001",
                "change_made": "edit",
                "additional_affected_slices": [],
            }
        ],
        "self_review": [
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "ok",
            }
        ],
    }
    input_path = _write_input(tmp_path, "1b_missing_fc.json", payload_1b)
    result = _run_writer_with_input(workspace, input_path)
    assert result.returncode == 0, result.stderr
    settled = json.loads((workspace / ".cross-agent-reviews/foo/spec/round-1b.json").read_text())
    assert settled["finding_lineage"] == []
    assert "LINEAGE_INCOMPLETE: R1-1-001: missing fix_criterion" in result.stderr


def test_1b_omits_lineage_for_unknown_affected_slice_id_and_warns(tmp_path):
    workspace = _setup_fast_workspace(tmp_path / "wf", review_profile="patch")
    _drive_to_1b_pending(
        workspace,
        tmp_path,
        findings_by_agent={1: [_lineage_finding(location="L1")]},
    )
    # The 1a slice_plan has 5 agents (ids 1..5). agent_id 6 passes the schema
    # (the schema allows 1..6) but is unknown to this plan, so the writer must
    # omit the lineage row and emit LINEAGE_INCOMPLETE.
    payload_1b = {
        "stage": "1b",
        "adjudications": [
            {
                "finding_id": "R1-1-001",
                "verdict": "accept",
                "reasoning": "fix",
                "fix_criterion": "c",
                "verification_target": "t",
            }
        ],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R1-1-001",
                "change_made": "edit",
                "additional_affected_slices": [6],
            }
        ],
        "self_review": [
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "ok",
            }
        ],
    }
    input_path = _write_input(tmp_path, "1b_bad_slice.json", payload_1b)
    result = _run_writer_with_input(workspace, input_path)
    assert result.returncode == 0, result.stderr
    settled = json.loads((workspace / ".cross-agent-reviews/foo/spec/round-1b.json").read_text())
    assert settled["finding_lineage"] == []
    assert "LINEAGE_INCOMPLETE: R1-1-001:" in result.stderr
    assert "6" in result.stderr


def test_1b_thorough_mode_omits_finding_lineage_field_entirely(workspace_with_state):
    # Default workspace is thorough mode (no --mode flag). Drive 1a + 1b.
    write_round(workspace_with_state, "round_1a_input.json")
    result = write_round(workspace_with_state, "round_1b_input.json")
    assert result.returncode == 0, result.stderr
    settled = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-1b.json").read_text()
    )
    assert "finding_lineage" not in settled


def test_1b_fast_mode_with_absent_review_profile_omits_finding_lineage(workspace_fast, tmp_path):
    # `workspace_fast` is initialised with --mode fast but NO --review-profile.
    # Spec §3.3: a fast block with no profile is legacy-shaped state; the
    # writer MUST NOT synthesize lineage for it.
    write_round(workspace_fast, "round_1a_input.json")  # 1 finding, not clean → manual 1b
    result = write_round(workspace_fast, "round_1b_input.json")
    assert result.returncode == 0, result.stderr
    settled = json.loads(
        (workspace_fast / ".cross-agent-reviews/foo/spec/round-1b.json").read_text()
    )
    assert "finding_lineage" not in settled


# ---------------------------------------------------------------------------
# finding_lineage emission on 2b settle (issue #22, Task 6)
#
# 2b lineage = carry-forward of each 1b lineage row (with latest_verification
# populated from the paired 2a verifications) PLUS one fresh row per accepted
# 2a finding. Same fast / profile-aware gate as 1b.
# ---------------------------------------------------------------------------


def _lineage_2a_agents_verifying_r1_1_001(
    *,
    extra_findings_by_agent: dict[int, list[dict]] | None = None,
    verification_status: str = "resolved",
    verification_evidence: str = "§3.2 now defines foo: string.",
) -> list[dict]:
    """Build a 2a `agents` list that verifies R1-1-001 on agent 1 and optionally
    adds new findings to some agents. Every other slice reports verified +
    clean. Suitable for use with the 5-slice _lineage_1a_slice_plan."""
    extra = extra_findings_by_agent or {}
    concerns = {
        1: ("Data model & schemas", "§3-§5"),
        2: ("Error handling & edge cases", "§6"),
        3: ("Acceptance criteria & testability", "§7-§8"),
        4: ("Cross-section consistency", "all"),
        5: ("Global coherence", "all"),
    }
    out: list[dict] = []
    for aid in range(1, 6):
        concern, slice_def = concerns[aid]
        findings = extra.get(aid, [])
        verifications = []
        if aid == 1:
            verifications = [
                {
                    "round_1_finding_id": "R1-1-001",
                    "status": verification_status,
                    "evidence": verification_evidence,
                }
            ]
        out.append(
            {
                "agent_id": aid,
                "concern": concern,
                "slice_definition": slice_def,
                "status": "issues_found" if findings else "verified",
                "findings": findings,
                "round_1_verifications": verifications,
            }
        )
    return out


def _drive_to_2b_pending_after_r1_1_001(
    workspace,
    tmp_path,
    *,
    extra_findings_by_agent: dict[int, list[dict]] | None = None,
    verification_status: str = "resolved",
    verification_evidence: str = "§3.2 now defines foo: string.",
    additional_affected_slices_1b: list[int] | None = None,
):
    """Drive 1a (one R1-1-001) → 1b (accept R1-1-001) → 2a (verify R1-1-001,
    plus any extra new findings). Leaves state at round_2b_pending."""
    # 1a
    _drive_to_1b_pending(
        workspace,
        tmp_path,
        findings_by_agent={1: [_lineage_finding(location="L1")]},
    )
    # 1b — accept R1-1-001
    payload_1b = {
        "stage": "1b",
        "adjudications": [
            {
                "finding_id": "R1-1-001",
                "verdict": "accept",
                "reasoning": "fix",
                "fix_criterion": "Define foo with a concrete type in §3.2.",
                "verification_target": "§3.2 declares foo: string.",
            }
        ],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R1-1-001",
                "change_made": "Defined foo as a string in §3.2.",
                "additional_affected_slices": additional_affected_slices_1b or [3],
            }
        ],
        "self_review": [
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "ok",
            }
        ],
    }
    input_path = _write_input(tmp_path, "1b_lineage_input.json", payload_1b)
    result = _run_writer_with_input(workspace, input_path)
    assert result.returncode == 0, result.stderr
    # 2a — verify R1-1-001
    payload_2a = {
        "stage": "2a",
        "agents": _lineage_2a_agents_verifying_r1_1_001(
            extra_findings_by_agent=extra_findings_by_agent,
            verification_status=verification_status,
            verification_evidence=verification_evidence,
        ),
    }
    input_path = _write_input(tmp_path, "2a_lineage_input.json", payload_2a)
    result = _run_writer_with_input(workspace, input_path)
    assert result.returncode == 0, result.stderr


def test_2b_carries_forward_every_1b_lineage_row_with_latest_verification(tmp_path):
    workspace = _setup_fast_workspace(tmp_path / "wf", review_profile="patch")
    # Clean 2a (R1-1-001 resolved, no new findings) → fast-mode auto-settle
    # writes round-2b.json in-process. The carry-forward path must also fire
    # on the auto-settle route, not only on a manually-authored 2b.
    _drive_to_2b_pending_after_r1_1_001(
        workspace,
        tmp_path,
        verification_status="resolved",
        verification_evidence="§3.2 now defines foo: string.",
    )
    settled = json.loads((workspace / ".cross-agent-reviews/foo/spec/round-2b.json").read_text())
    # Pull the 1b row we're carrying forward so the assertion checks every
    # writer-derived field carries over correctly.
    row_1b = json.loads((workspace / ".cross-agent-reviews/foo/spec/round-1b.json").read_text())[
        "finding_lineage"
    ][0]
    assert settled["finding_lineage"] == [
        {
            "lineage_id": "L-2b-R1-1-001",
            "original_finding_id": "R1-1-001",
            "originating_stage": "1a",
            "originating_agent_id": 1,
            "originating_slice": row_1b["originating_slice"],
            "affected_location": row_1b["affected_location"],
            "affected_slices": row_1b["affected_slices"],
            "fix_criterion": row_1b["fix_criterion"],
            "verification_target": row_1b["verification_target"],
            "prior_lineage_id": "L-1b-R1-1-001",
            "latest_verification": {
                "status": "resolved",
                "evidence": "§3.2 now defines foo: string.",
            },
        }
    ]


def test_2b_adds_fresh_row_for_each_accepted_2a_finding(tmp_path):
    workspace = _setup_fast_workspace(tmp_path / "wf", review_profile="patch")
    # 2a introduces a new gap on agent 1 → R2-1-001.
    new_finding = _lineage_finding(
        location="§4.1 line 10",
        severity="gap",
        finding="Gap discovered by 2a.",
    )
    _drive_to_2b_pending_after_r1_1_001(
        workspace,
        tmp_path,
        extra_findings_by_agent={1: [new_finding]},
    )
    payload_2b = {
        "stage": "2b",
        "adjudications": [
            {
                "finding_id": "R2-1-001",
                "verdict": "accept",
                "reasoning": "real gap",
                "fix_criterion": "Specify behaviour in §4.1.",
                "verification_target": "§4.1 now lists the behaviour.",
            }
        ],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R2-1-001",
                "change_made": "Specified behaviour in §4.1.",
                "additional_affected_slices": [2],
            }
        ],
        "self_review": [
            {
                "finding_id": "R2-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "ok",
            }
        ],
    }
    input_path = _write_input(tmp_path, "2b_fresh.json", payload_2b)
    result = _run_writer_with_input(workspace, input_path)
    assert result.returncode == 0, result.stderr
    settled = json.loads((workspace / ".cross-agent-reviews/foo/spec/round-2b.json").read_text())
    assert len(settled["finding_lineage"]) == 2
    # Carry-forward row from 1b.
    carry = next(r for r in settled["finding_lineage"] if r["original_finding_id"] == "R1-1-001")
    assert carry["lineage_id"] == "L-2b-R1-1-001"
    assert carry["prior_lineage_id"] == "L-1b-R1-1-001"
    assert carry["originating_stage"] == "1a"
    # Fresh row for the new 2a finding.
    fresh = next(r for r in settled["finding_lineage"] if r["original_finding_id"] == "R2-1-001")
    assert fresh == {
        "lineage_id": "L-2b-R2-1-001",
        "original_finding_id": "R2-1-001",
        "originating_stage": "2a",
        "originating_agent_id": 1,
        "originating_slice": "Data model & schemas",
        "affected_location": "§4.1 line 10",
        "affected_slices": [1, 2],
        "fix_criterion": "Specify behaviour in §4.1.",
        "verification_target": "§4.1 now lists the behaviour.",
        "prior_lineage_id": None,
        "latest_verification": None,
    }


def test_2b_carry_forward_omits_row_when_2a_lacks_verification(tmp_path):
    workspace = _setup_fast_workspace(tmp_path / "wf", review_profile="patch")
    # Give 2a one new finding so it isn't clean → the writer leaves state at
    # round_2b_pending instead of auto-settling, so we can author a manual 2b.
    extra = _lineage_finding(location="§5", finding="2a noise.", severity="gap")
    _drive_to_2b_pending_after_r1_1_001(
        workspace,
        tmp_path,
        extra_findings_by_agent={2: [extra]},
    )
    # Hand-edit round-1b.json on disk: inject a phantom lineage row whose
    # original_finding_id does not appear in the paired 2a's
    # round_1_verifications. The writer should omit it from the 2b carry-
    # forward and emit a LINEAGE_INCOMPLETE marker; the legitimate
    # carry-forward for R1-1-001 stays.
    round_1b_path = workspace / ".cross-agent-reviews/foo/spec/round-1b.json"
    round_1b = json.loads(round_1b_path.read_text())
    phantom = dict(round_1b["finding_lineage"][0])
    phantom["lineage_id"] = "L-1b-R1-2-001"
    phantom["original_finding_id"] = "R1-2-001"
    round_1b["finding_lineage"].append(phantom)
    round_1b_path.write_text(json.dumps(round_1b))
    # Reject the 2a finding so no fresh lineage row is added; the assertion
    # below sees only carry-forward output.
    payload_2b = {
        "stage": "2b",
        "adjudications": [
            {
                "finding_id": "R2-2-001",
                "verdict": "reject",
                "reasoning": "Not blocking.",
            }
        ],
        "rejected_findings": [],
        "changelog": [],
        "self_review": [],
    }
    input_path = _write_input(tmp_path, "2b_phantom.json", payload_2b)
    result = _run_writer_with_input(workspace, input_path)
    # Writer must not crash on a missing verification: it omits the row and
    # warns instead.
    assert result.returncode == 0, result.stderr
    settled = json.loads((workspace / ".cross-agent-reviews/foo/spec/round-2b.json").read_text())
    assert len(settled["finding_lineage"]) == 1
    assert settled["finding_lineage"][0]["original_finding_id"] == "R1-1-001"
    assert "LINEAGE_INCOMPLETE: R1-2-001: missing 2a verification" in result.stderr


def test_2b_thorough_mode_omits_finding_lineage_field_entirely(workspace_with_state):
    # Default workspace is thorough mode (no --mode flag). Drive 1a → 1b → 2a → 2b.
    write_round(workspace_with_state, "round_1a_input.json")
    write_round(workspace_with_state, "round_1b_input.json")
    write_round(workspace_with_state, "round_2a_input.json")
    result = write_round(workspace_with_state, "round_2b_input.json")
    assert result.returncode == 0, result.stderr
    settled = json.loads(
        (workspace_with_state / ".cross-agent-reviews/foo/spec/round-2b.json").read_text()
    )
    assert "finding_lineage" not in settled
