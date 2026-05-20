"""End-to-end single-host walkthrough: init → 1a → 1b → 2a → 2b → 3a → 3b → 3c."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPERS = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers"
WRITE = HELPERS / "cr_state_write.py"
INIT = HELPERS / "cr_state_init.py"


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


def test_full_pipeline_terminates_ready(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "docs/specs").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "tests/fixtures/artifacts/spec.md", tmp_path / "docs/specs/foo-design.md"
    )
    schema_dst = tmp_path / "plugin/skills/cr/_shared/schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "plugin/skills/cr/_shared/schema", schema_dst)
    artifact = tmp_path / "docs/specs/foo-design.md"
    init = run(
        HELPERS / "cr_state_init.py",
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=tmp_path,
        stdin="",
    )
    assert init.returncode == 0, init.stderr

    fixtures = REPO_ROOT / "tests/fixtures/state_write_inputs"
    for stage_input in [
        "round_1a_input.json",
        "round_1b_input.json",
        "round_2a_input.json",
        "round_2b_input.json",
        "round_3a_input_blocker.json",
        "round_3b_input_adjudicate.json",
    ]:
        result = run(
            HELPERS / "cr_state_write.py",
            [
                "--slug",
                "foo",
                "--artifact-type",
                "spec",
                "--artifact-path",
                "docs/specs/foo-design.md",
                "--input",
                str(fixtures / stage_input),
            ],
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"{stage_input}: {result.stderr}"

    state = json.loads((tmp_path / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "ready_for_implementation"
    assert state["spec"]["completed_rounds"] == ["1a", "1b", "2a", "2b", "3a", "3b"]

    final_3b = json.loads((tmp_path / ".cross-agent-reviews/foo/spec/round-3b.json").read_text())
    # Non-clean 3a (one blocker_found agent) → round_3b_pending → 3b rejects the
    # blocker → zero accepted findings → final_status READY_FOR_IMPLEMENTATION.
    assert final_3b["final_status"] == "READY_FOR_IMPLEMENTATION"


def test_full_pipeline_terminates_ready_for_plan(tmp_path):
    """Acceptance criterion #3 explicitly requires the zero-paste workflow
    for **both** spec and plan. This exercises the plan path under
    plan-only init (no `state.spec`, hence no cross-artifact slice — that
    path is exercised by `test_round_1a_blocker_envelope_with_cross_artifact_slice_validates`
    in `test_placeholder_hallucination.py`). The script-level handoffs are
    identical to the spec workflow, so we reuse the same fixture inputs."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "tests/fixtures/artifacts/plan.md", tmp_path / "docs/plans/foo-plan.md")
    schema_dst = tmp_path / "plugin/skills/cr/_shared/schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "plugin/skills/cr/_shared/schema", schema_dst)
    artifact = tmp_path / "docs/plans/foo-plan.md"
    init = run(
        HELPERS / "cr_state_init.py",
        ["--artifact-path", str(artifact), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=tmp_path,
        stdin="y\n",
    )
    assert init.returncode == 0, init.stderr

    fixtures = REPO_ROOT / "tests/fixtures/state_write_inputs"
    for stage_input in [
        "round_1a_input.json",
        "round_1b_input.json",
        "round_2a_input.json",
        "round_2b_input.json",
        "round_3a_input_blocker.json",
        "round_3b_input_adjudicate.json",
    ]:
        result = run(
            HELPERS / "cr_state_write.py",
            [
                "--slug",
                "foo",
                "--artifact-type",
                "plan",
                "--artifact-path",
                "docs/plans/foo-plan.md",
                "--input",
                str(fixtures / stage_input),
            ],
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"plan-{stage_input}: {result.stderr}"

    state = json.loads((tmp_path / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["plan"]["current_stage"] == "ready_for_implementation"
    assert state["plan"]["completed_rounds"] == ["1a", "1b", "2a", "2b", "3a", "3b"]
    final_3b = json.loads((tmp_path / ".cross-agent-reviews/foo/plan/round-3b.json").read_text())
    assert final_3b["final_status"] == "READY_FOR_IMPLEMENTATION"


def test_full_pipeline_terminates_at_clean_3a(tmp_path):
    """A clean Round 3a terminates the pipeline immediately: state lands at
    ready_for_implementation with the five-round clean_3a shape, and no
    round-3b.json is ever written."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "docs/specs").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "tests/fixtures/artifacts/spec.md", tmp_path / "docs/specs/foo-design.md"
    )
    schema_dst = tmp_path / "plugin/skills/cr/_shared/schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "plugin/skills/cr/_shared/schema", schema_dst)
    artifact = tmp_path / "docs/specs/foo-design.md"
    init = run(
        HELPERS / "cr_state_init.py",
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=tmp_path,
        stdin="",
    )
    assert init.returncode == 0, init.stderr

    fixtures = REPO_ROOT / "tests/fixtures/state_write_inputs"
    # Walk only 1a..3a; round_3a_input.json is all-ship_ready (clean).
    for stage_input in [
        "round_1a_input.json",
        "round_1b_input.json",
        "round_2a_input.json",
        "round_2b_input.json",
        "round_3a_input.json",
    ]:
        result = run(
            HELPERS / "cr_state_write.py",
            [
                "--slug",
                "foo",
                "--artifact-type",
                "spec",
                "--artifact-path",
                "docs/specs/foo-design.md",
                "--input",
                str(fixtures / stage_input),
            ],
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"{stage_input}: {result.stderr}"

    state = json.loads((tmp_path / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "ready_for_implementation"
    assert state["spec"]["completed_rounds"] == ["1a", "1b", "2a", "2b", "3a"]
    assert not (tmp_path / ".cross-agent-reviews/foo/spec/round-3b.json").exists()


# ---------------------------------------------------------------------------
# Shared helpers for 3c integration tests
# ---------------------------------------------------------------------------


def _make_spec_workspace(root):
    """Initialise a git repo with the canonical spec artifact and schema copies."""
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    (root / "docs/specs").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "tests/fixtures/artifacts/spec.md", root / "docs/specs/foo-design.md")
    schema_dst = root / "plugin/skills/cr/_shared/schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "plugin/skills/cr/_shared/schema", schema_dst)


def _drive_to_3c_pending(workspace):
    """Init workspace and drive 1a → 1b → 2a → 2b → 3a(blocker) → 3b(accept)
    so current_stage == round_3c_pending."""
    artifact = workspace / "docs/specs/foo-design.md"
    init = run(
        INIT,
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    assert init.returncode == 0, init.stderr
    fixtures = REPO_ROOT / "tests/fixtures/state_write_inputs"
    for stage_input in [
        "round_1a_input.json",
        "round_1b_input.json",
        "round_2a_input.json",
        "round_2b_input.json",
        "round_3a_input_blocker.json",
        "round_3b_input_accept.json",
    ]:
        r = run(
            WRITE,
            [
                "--slug",
                "foo",
                "--artifact-type",
                "spec",
                "--artifact-path",
                "docs/specs/foo-design.md",
                "--input",
                str(fixtures / stage_input),
            ],
            cwd=workspace,
        )
        assert r.returncode == 0, f"{stage_input}: {r.stderr}"


def _write_3c(workspace, input_fixture):
    fixtures = REPO_ROOT / "tests/fixtures/state_write_inputs"
    return run(
        WRITE,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(fixtures / input_fixture),
        ],
        cwd=workspace,
    )


# ---------------------------------------------------------------------------
# Round 3c integration tests
# ---------------------------------------------------------------------------


def test_pipeline_terminates_via_3c(tmp_path):
    """Drive 1a→3b-accept, assert round_3c_pending, then pass 3c and assert
    the pipeline terminates at ready_for_implementation with the via_3c shape."""
    _make_spec_workspace(tmp_path)
    _drive_to_3c_pending(tmp_path)

    state = json.loads((tmp_path / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_3c_pending"

    result = _write_3c(tmp_path, "round_3c_input_pass.json")
    assert result.returncode == 0, result.stderr

    state = json.loads((tmp_path / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "ready_for_implementation"
    assert set(state["spec"]["completed_rounds"]) == {"1a", "1b", "2a", "2b", "3a", "3b", "3c"}

    env = json.loads((tmp_path / ".cross-agent-reviews/foo/spec/round-3c.json").read_text())
    assert env["final_status"] == "CORRECTED_AND_READY"
    assert state["spec"]["content_hash"] == env["verified_content_hash"]


def test_3c_fail_then_pass_records_prior_attempt(tmp_path):
    """A failed 3c (attempt-001) followed by a recovery edit and a passing 3c
    records the failed attempt in prior_attempts and refreshes content_hash."""
    _make_spec_workspace(tmp_path)
    _drive_to_3c_pending(tmp_path)

    # Capture the content_hash after 3b (before any 3c run).
    post_3b_hash = json.loads((tmp_path / ".cross-agent-reviews/foo/state.json").read_text())[
        "spec"
    ]["content_hash"]

    # First 3c run: fails; writes round-3c-attempt-001.json, state unchanged.
    result = _write_3c(tmp_path, "round_3c_input_fail.json")
    assert result.returncode == 0, result.stderr
    attempt_file = tmp_path / ".cross-agent-reviews/foo/spec/round-3c-attempt-001.json"
    assert attempt_file.exists()

    # Operator recovery edit: mutate artifact bytes so the rerun guard does
    # not block the second run (3c rerun against byte-identical artifact is
    # rejected by the rerun guard in cr_state_write.py).
    artifact = tmp_path / "docs/specs/foo-design.md"
    artifact.write_text(artifact.read_text() + "\n<!-- integration recovery edit -->\n")

    # Second 3c run: passes against the new bytes.
    result = _write_3c(tmp_path, "round_3c_input_pass.json")
    assert result.returncode == 0, result.stderr

    env = json.loads((tmp_path / ".cross-agent-reviews/foo/spec/round-3c.json").read_text())
    assert len(env["prior_attempts"]) == 1
    assert env["prior_attempts"][0]["attempt_number"] == 1

    state = json.loads((tmp_path / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["content_hash"] == env["verified_content_hash"]
    # content_hash was refreshed to the post-recovery bytes, not the post-3b bytes.
    assert state["spec"]["content_hash"] != post_3b_hash


# ---------------------------------------------------------------------------
# Task 12 — fast/patch narrow happy path (issue #22)
#
# End-to-end exercise of the impact-routing happy path: 1a (one finding on
# slice 1) → 1b accept + impact slice 3 → narrow 2a covering {1,3,5} →
# auto-settled 2b → narrow 3a covering {1,3,5} (all ship_ready) → terminal
# clean_3a. Pins:
#   - The writer never emits BLOCKED on the happy path.
#   - finding_lineage carries from 1b through 2b with the expected shape.
#   - The terminal state is reached without a 3b ever running.
# ---------------------------------------------------------------------------


def _init_fast_patch(workspace):
    artifact = workspace / "docs/specs/foo-design.md"
    return run(
        INIT,
        [
            "--artifact-path",
            str(artifact),
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
            "--mode",
            "fast",
            "--review-profile",
            "patch",
        ],
        cwd=workspace,
        stdin="",
    )


def _write_input_file(workspace, name, payload):
    path = workspace / name
    path.write_text(json.dumps(payload))
    return path


def _write_round(workspace, input_path):
    return run(
        WRITE,
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


_HAPPY_SLICE_PLAN = [
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

_HAPPY_CONCERNS = {
    1: ("Data model & schemas", "§3-§5"),
    2: ("Error handling & edge cases", "§6"),
    3: ("Acceptance criteria & testability", "§7-§8"),
    4: ("Cross-section consistency", "all"),
    5: ("Global coherence", "all"),
}


def test_patch_fast_narrow_2a_happy_path(tmp_path):
    """Full pipeline 1a → 1b (accept + impact slice 3) → narrow 2a {1,3,5}
    (auto-settled) → narrow 3a {1,3,5} (clean) → terminal clean_3a.

    The writer must never emit BLOCKED on this path: every step's stderr
    must be free of any BLOCKED:* marker. The 1b and 2b envelopes must
    carry finding_lineage with the expected carry-forward shape. The final
    state lands at ready_for_implementation via the clean_3a route (no
    round-3b.json on disk)."""
    _make_spec_workspace(tmp_path)
    assert _init_fast_patch(tmp_path).returncode == 0

    blocked: list[str] = []

    def _check(result, stage):
        # Capture-and-defer: collect each round's stderr so the final
        # assertion names every offending stage (not just the first).
        assert result.returncode == 0, f"{stage}: {result.stderr}"
        if "BLOCKED:" in result.stderr:
            blocked.append(f"{stage}: {result.stderr.strip()}")

    # 1a: one finding on agent 1, others clean.
    finding = {
        "location": "§3.2 line 47",
        "severity": "blocker",
        "finding": "Field foo is undefined.",
        "why_it_matters": "Implementer cannot decide its type.",
        "suggested_direction": "Define foo in §3.2.",
    }
    agents_1a = []
    for aid in range(1, 6):
        concern, slice_def = _HAPPY_CONCERNS[aid]
        agents_1a.append(
            {
                "agent_id": aid,
                "concern": concern,
                "slice_definition": slice_def,
                "status": "findings_found" if aid == 1 else "clean",
                "findings": [finding] if aid == 1 else [],
            }
        )
    input_1a = _write_input_file(
        tmp_path,
        "happy_1a.json",
        {"stage": "1a", "slice_plan": _HAPPY_SLICE_PLAN, "agents": agents_1a},
    )
    _check(_write_round(tmp_path, input_1a), "1a")

    # 1b: accept R1-1-001 with complete lineage author fields + impact slice 3.
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
    input_1b = _write_input_file(tmp_path, "happy_1b.json", payload_1b)
    _check(_write_round(tmp_path, input_1b), "1b")

    settled_1b = json.loads((tmp_path / ".cross-agent-reviews/foo/spec/round-1b.json").read_text())
    # 1b lineage shape: one row, originating_slice = "Data model & schemas",
    # affected_slices = [1, 3] (origin + impact).
    assert settled_1b["finding_lineage"] == [
        {
            "lineage_id": "L-1b-R1-1-001",
            "original_finding_id": "R1-1-001",
            "originating_stage": "1a",
            "originating_agent_id": 1,
            "originating_slice": "Data model & schemas",
            "affected_location": "§3.2 line 47",
            "affected_slices": [1, 3],
            "fix_criterion": "Define foo with a concrete type in §3.2.",
            "verification_target": "§3.2 declares foo: string.",
            "prior_lineage_id": None,
            "latest_verification": None,
        }
    ]

    # 2a: narrow route {1,3,5}. Agent 1 verifies R1-1-001 as resolved; agents
    # 3 and 5 are clean. A clean 2a in fast mode auto-settles 2b in-process.
    agents_2a = []
    for aid in (1, 3, 5):
        concern, slice_def = _HAPPY_CONCERNS[aid]
        verifications = []
        if aid == 1:
            verifications = [
                {
                    "round_1_finding_id": "R1-1-001",
                    "status": "resolved",
                    "evidence": "§3.2 now defines foo: string.",
                }
            ]
        agents_2a.append(
            {
                "agent_id": aid,
                "concern": concern,
                "slice_definition": slice_def,
                "status": "verified",
                "findings": [],
                "round_1_verifications": verifications,
            }
        )
    input_2a = _write_input_file(tmp_path, "happy_2a.json", {"stage": "2a", "agents": agents_2a})
    _check(_write_round(tmp_path, input_2a), "2a")

    # 2b must exist (auto-settled) and carry forward the 1b lineage row with
    # latest_verification populated from the 2a verification.
    round_2b_path = tmp_path / ".cross-agent-reviews/foo/spec/round-2b.json"
    assert round_2b_path.exists(), "fast/patch clean 2a must auto-settle 2b"
    settled_2b = json.loads(round_2b_path.read_text())
    assert settled_2b["finding_lineage"] == [
        {
            "lineage_id": "L-2b-R1-1-001",
            "original_finding_id": "R1-1-001",
            "originating_stage": "1a",
            "originating_agent_id": 1,
            "originating_slice": "Data model & schemas",
            "affected_location": "§3.2 line 47",
            "affected_slices": [1, 3],
            "fix_criterion": "Define foo with a concrete type in §3.2.",
            "verification_target": "§3.2 declares foo: string.",
            "prior_lineage_id": "L-1b-R1-1-001",
            "latest_verification": {
                "status": "resolved",
                "evidence": "§3.2 now defines foo: string.",
            },
        }
    ]

    state = json.loads((tmp_path / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "round_3a_pending"

    # 3a: narrow {1,3,5}, all ship_ready (clean). Routes straight to
    # ready_for_implementation; no 3b is ever written.
    agents_3a = []
    for aid in (1, 3, 5):
        concern, slice_def = _HAPPY_CONCERNS[aid]
        agents_3a.append(
            {
                "agent_id": aid,
                "concern": concern,
                "slice_definition": slice_def,
                "status": "ship_ready",
                "findings": [],
                "round_1_verifications": [],
            }
        )
    input_3a = _write_input_file(tmp_path, "happy_3a.json", {"stage": "3a", "agents": agents_3a})
    _check(_write_round(tmp_path, input_3a), "3a")

    assert not blocked, "writer emitted BLOCKED on happy path: " + "; ".join(blocked)

    state = json.loads((tmp_path / ".cross-agent-reviews/foo/state.json").read_text())
    assert state["spec"]["current_stage"] == "ready_for_implementation"
    assert state["spec"]["completed_rounds"] == ["1a", "1b", "2a", "2b", "3a"]
    assert not (tmp_path / ".cross-agent-reviews/foo/spec/round-3b.json").exists()
