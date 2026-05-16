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
