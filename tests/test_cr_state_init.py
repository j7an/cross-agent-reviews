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
SCRIPT = REPO_ROOT / "scripts" / "cr_state_init.py"


def run(args, cwd, stdin=None, env=None):
    """Invoke the script with PYTHONPATH pointing at the repo so `from scripts._cr_lib import …` works.

    Inherits `os.environ` so pytest-cov's COVERAGE_PROCESS_START reaches the
    subprocess (cross-cutting subprocess-coverage convention)."""
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
