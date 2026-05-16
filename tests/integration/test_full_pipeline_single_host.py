"""End-to-end single-host walkthrough: init → 1a → 1b → 2a → 2b → 3a → 3b."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPERS = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers"


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
