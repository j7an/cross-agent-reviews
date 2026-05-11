"""Tests for cr_state_init.py."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers" / "cr_state_init.py"


def run(args, cwd, stdin=None, env=None):
    """Invoke the script in script mode (sys.path[0] = `_helpers/`).

    Inherits `os.environ` so pytest-cov's COVERAGE_PROCESS_START reaches
    the subprocess (cross-cutting subprocess-coverage convention). Setting
    PYTHONPATH=REPO_ROOT lets `sitecustomize.py` (at the repo root) load
    so `coverage.process_startup()` runs in each subprocess."""
    full_env = {**os.environ, **(env or {})}
    full_env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=full_env,
        check=False,
    )


@pytest.fixture
def workspace(tmp_path):
    """Bare project workspace: git-init'd, with the artifact fixtures and a stub plugin/skill schema layout."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    # copy artifact
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "tests" / "fixtures" / "artifacts" / "spec.md",
        tmp_path / "docs" / "specs" / "foo-design.md",
    )
    (tmp_path / "docs" / "plans").mkdir()
    shutil.copy(
        REPO_ROOT / "tests" / "fixtures" / "artifacts" / "plan.md",
        tmp_path / "docs" / "plans" / "foo-plan.md",
    )
    # link schema dir for find_repo_root + schema discovery
    schema_src = REPO_ROOT / "plugin" / "skills" / "cr" / "_shared" / "schema"
    schema_dst = tmp_path / "plugin" / "skills" / "cr" / "_shared" / "schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(schema_src, schema_dst)
    return tmp_path


def test_creates_state_json_for_spec(workspace):
    artifact = workspace / "docs" / "specs" / "foo-design.md"
    result = run(
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    assert result.returncode == 0, result.stderr

    state_path = workspace / ".cross-agent-reviews" / "foo" / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["slug"] == "foo"
    assert state["spec"]["path"] == str(artifact.relative_to(workspace))
    assert state["spec"]["current_stage"] == "round_1a_pending"
    assert state["spec"]["completed_rounds"] == []
    assert state["spec"]["content_hash"].startswith("sha256:")


def test_init_from_subdirectory_hashes_correct_file(workspace):
    """Running cr_state_init from a repo subdirectory must hash the artifact
    bytes correctly (against its absolute path) even though state.json
    stores the repo-relative path. Hashing the relative path against
    Path.cwd() in a subdirectory would either fail or read the wrong file.
    """
    artifact = workspace / "docs" / "specs" / "foo-design.md"
    expected_bytes = artifact.read_bytes()
    expected_hash = "sha256:" + hashlib.sha256(expected_bytes).hexdigest()
    subdir = workspace / "docs"
    result = run(
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=subdir,
        stdin="",
    )
    assert result.returncode == 0, result.stderr
    state = json.loads((workspace / ".cross-agent-reviews" / "foo" / "state.json").read_text())
    assert state["spec"]["content_hash"] == expected_hash
    assert state["spec"]["path"] == str(artifact.relative_to(workspace))


def test_emits_state_to_stdout(workspace):
    artifact = workspace / "docs" / "specs" / "foo-design.md"
    result = run(
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    payload = json.loads(result.stdout)
    assert payload["slug"] == "foo"


def test_plan_only_warns_and_requires_confirmation(workspace):
    artifact = workspace / "docs" / "plans" / "foo-plan.md"
    # decline confirmation
    result = run(
        ["--artifact-path", str(artifact), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="n\n",
    )
    assert result.returncode != 0
    assert "cross-artifact placeholder check is disabled" in result.stderr
    assert not (workspace / ".cross-agent-reviews" / "foo").exists()


def test_plan_only_accepted_creates_state_without_spec_hash(workspace):
    artifact = workspace / "docs" / "plans" / "foo-plan.md"
    result = run(
        ["--artifact-path", str(artifact), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="y\n",
    )
    assert result.returncode == 0
    state = json.loads((workspace / ".cross-agent-reviews" / "foo" / "state.json").read_text())
    assert "spec_hash_at_start" not in state["plan"]


def test_plan_after_finished_spec_captures_spec_hash(workspace):
    spec = workspace / "docs" / "specs" / "foo-design.md"
    plan = workspace / "docs" / "plans" / "foo-plan.md"
    # spec init
    run(
        ["--artifact-path", str(spec), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    # mark spec as finished by hand-editing state (simulating a completed pipeline)
    state_path = workspace / ".cross-agent-reviews" / "foo" / "state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "ready_for_implementation"
    state["spec"]["completed_rounds"] = ["1a", "1b", "2a", "2b", "3a", "3b"]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    # now plan init
    result = run(
        ["--artifact-path", str(plan), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    assert result.returncode == 0, result.stderr
    state = json.loads(state_path.read_text())
    assert state["plan"]["spec_hash_at_start"] == state["spec"]["content_hash"]


def test_spec_init_refused_when_plan_block_already_exists(workspace):
    """§11.3 mandates spec-first ordering. A plan-only slug must NOT accept a
    later spec init — doing so would leave state.plan.spec_hash_at_start
    absent, violating the both-blocks-imply-anchor invariant."""
    plan = workspace / "docs" / "plans" / "foo-plan.md"
    spec = workspace / "docs" / "specs" / "foo-design.md"
    # plan-only init first
    run(
        ["--artifact-path", str(plan), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="y\n",
    )
    # now try to add a spec block to the same slug
    result = run(
        ["--artifact-path", str(spec), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    assert result.returncode != 0
    assert "spec-first" in result.stderr.lower() or "already has a plan" in result.stderr.lower()
    state = json.loads((workspace / ".cross-agent-reviews" / "foo" / "state.json").read_text())
    assert "spec" not in state


def test_plan_refused_when_spec_in_flight(workspace):
    spec = workspace / "docs" / "specs" / "foo-design.md"
    plan = workspace / "docs" / "plans" / "foo-plan.md"
    run(
        ["--artifact-path", str(spec), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    # spec stays in round_1a_pending (default after init)
    result = run(
        ["--artifact-path", str(plan), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    assert result.returncode != 0
    assert (
        "spec review must be terminal" in result.stderr.lower()
        or "in-flight" in result.stderr.lower()
    )


def test_plan_refused_when_spec_in_flight_pins_section_message(workspace):
    """Regression guard: the §11.3 ordering rule (plan blocked when spec is
    in-flight) must always emit the canonical stderr message. Consumers
    grep this string; rewording it would break them."""
    spec = workspace / "docs" / "specs" / "foo-design.md"
    plan = workspace / "docs" / "plans" / "foo-plan.md"
    run(
        ["--artifact-path", str(spec), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    # spec stays in round_1a_pending after init
    result = run(
        ["--artifact-path", str(plan), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    assert result.returncode == 1
    assert "spec review must be terminal before a plan review can begin (§11.3)" in result.stderr


def _walk_block_to_terminal(state_path: Path, block_key: str) -> None:
    """Hand-edit state.json to mark `block_key` as terminal (post-3b).

    Mirrors the simulation already used by
    `test_plan_after_finished_spec_captures_spec_hash` — we don't actually
    drive the round-write helpers here; we just need a state file that
    looks finished so the next init hits the terminal-reinit branch."""
    state = json.loads(state_path.read_text())
    state[block_key]["current_stage"] = "ready_for_implementation"
    state[block_key]["completed_rounds"] = ["1a", "1b", "2a", "2b", "3a", "3b"]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def test_terminal_plan_reinit_refused_when_spec_back_in_flight(workspace):
    """The §11.3 ordering rule must hold on the terminal-reinit branch too.

    Sequence reproduces the reviewer-found attack:
      1. Init spec, walk to terminal.
      2. Init plan (captures spec hash), walk to terminal.
      3. Reinit terminal spec (operator confirmation 'y') → spec returns to
         round_1a_pending. Plan block is left alone (still terminal).
      4. Reinit terminal plan (operator confirmation 'y') → MUST be refused,
         because the spec block is now in-flight.

    Without the helper-hoist, step 4 silently archived the old plan and
    created a fresh round_1a_pending plan block whose `spec_hash_at_start`
    captured the now-stale spec content_hash — defeating drift detection."""
    spec = workspace / "docs" / "specs" / "foo-design.md"
    plan = workspace / "docs" / "plans" / "foo-plan.md"
    state_path = workspace / ".cross-agent-reviews" / "foo" / "state.json"

    # step 1: spec init + walk to terminal
    run(
        ["--artifact-path", str(spec), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    _walk_block_to_terminal(state_path, "spec")

    # step 2: plan init + walk to terminal
    run(
        ["--artifact-path", str(plan), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    _walk_block_to_terminal(state_path, "plan")
    state_before_plan_reinit = json.loads(state_path.read_text())
    plan_hash_before = state_before_plan_reinit["plan"]["content_hash"]
    plan_started_before = state_before_plan_reinit["plan"]["started_at"]

    # step 3: reinit terminal spec → spec returns to round_1a_pending
    result_spec = run(
        ["--artifact-path", str(spec), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="y\n",
    )
    assert result_spec.returncode == 0, result_spec.stderr
    state_after_spec_reinit = json.loads(state_path.read_text())
    assert state_after_spec_reinit["spec"]["current_stage"] == "round_1a_pending"
    # plan block left alone
    assert state_after_spec_reinit["plan"]["current_stage"] == "ready_for_implementation"

    # step 4: reinit terminal plan → MUST be refused (spec is in-flight)
    result_plan = run(
        ["--artifact-path", str(plan), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="y\n",
    )
    assert result_plan.returncode == 1, result_plan.stderr
    assert (
        "spec review must be terminal before a plan review can begin (§11.3)" in result_plan.stderr
    )

    # No archive happened — old terminal plan block preserved verbatim
    state_after_refused = json.loads(state_path.read_text())
    assert state_after_refused["plan"]["current_stage"] == "ready_for_implementation"
    assert state_after_refused["plan"]["content_hash"] == plan_hash_before
    assert state_after_refused["plan"]["started_at"] == plan_started_before
    archives = list((workspace / ".cross-agent-reviews" / "foo").glob(".archive-*"))
    # only the spec reinit's archive should exist (1 archive); none for plan
    plan_archives = [a for a in archives if (a / "plan").exists()]
    assert plan_archives == []


def test_in_flight_collision_refused(workspace):
    artifact = workspace / "docs" / "specs" / "foo-design.md"
    run(
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    # second init for same artifact type while still in_flight
    result = run(
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    assert result.returncode != 0
    assert "in-flight" in result.stderr.lower()


def test_terminal_spec_archived_on_reinit(workspace):
    artifact = workspace / "docs" / "specs" / "foo-design.md"
    run(
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    state_path = workspace / ".cross-agent-reviews" / "foo" / "state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "ready_for_implementation"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    # write a sentinel round file under spec/
    spec_dir = workspace / ".cross-agent-reviews" / "foo" / "spec"
    spec_dir.mkdir(exist_ok=True)
    (spec_dir / "round-1a.json").write_text('{"sentinel": true}')
    # confirm archive on stdin
    result = run(
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="y\n",
    )
    assert result.returncode == 0
    archives = list((workspace / ".cross-agent-reviews" / "foo").glob(".archive-*"))
    assert len(archives) == 1
    assert (archives[0] / "spec" / "round-1a.json").exists()
    # new spec block exists, fresh
    state = json.loads(state_path.read_text())
    assert state["spec"]["current_stage"] == "round_1a_pending"


def test_gitignore_prompt_appends_on_yes(workspace):
    artifact = workspace / "docs" / "specs" / "foo-design.md"
    result = run(
        ["--artifact-path", str(artifact), "--artifact-type", "spec"], cwd=workspace, stdin="y\n"
    )
    assert result.returncode == 0, result.stderr
    gi = (workspace / ".gitignore").read_text() if (workspace / ".gitignore").exists() else ""
    assert ".cross-agent-reviews/" in gi


def test_gitignore_prompt_skipped_when_already_present(workspace):
    (workspace / ".gitignore").write_text(".cross-agent-reviews/\n")
    artifact = workspace / "docs" / "specs" / "foo-design.md"
    result = run(
        ["--artifact-path", str(artifact), "--artifact-type", "spec"], cwd=workspace, stdin=""
    )
    assert result.returncode == 0
