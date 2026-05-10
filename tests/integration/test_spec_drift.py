"""Spec edit mid-plan-review triggers SPEC_DRIFT_DETECTED."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INIT = REPO_ROOT / "scripts" / "cr_state_init.py"
READ = REPO_ROOT / "scripts" / "cr_state_read.py"


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


def test_spec_change_triggers_drift(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "tests/fixtures/artifacts/spec.md", tmp_path / "docs/specs/foo-design.md"
    )
    shutil.copy(REPO_ROOT / "tests/fixtures/artifacts/plan.md", tmp_path / "docs/plans/foo-plan.md")
    schema_dst = tmp_path / "plugin/skills/cr/_shared/schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "plugin/skills/cr/_shared/schema", schema_dst)

    spec = tmp_path / "docs/specs/foo-design.md"
    plan = tmp_path / "docs/plans/foo-plan.md"
    run(
        INIT,
        ["--artifact-path", str(spec), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=tmp_path,
        stdin="",
    )
    # mark spec terminal
    state_path = tmp_path / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "ready_for_implementation"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    run(
        INIT,
        ["--artifact-path", str(plan), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=tmp_path,
        stdin="",
    )

    # baseline drift check — clean
    clean = run(READ, ["--slug", "foo", "--check-spec-drift"], cwd=tmp_path)
    assert clean.returncode == 0
    assert json.loads(clean.stdout)["spec_drift"] is False

    # mutate the spec
    spec.write_text(spec.read_text() + "\n## Mutation\n")
    drift = run(READ, ["--slug", "foo", "--check-spec-drift"], cwd=tmp_path)
    assert drift.returncode == 2
    assert "SPEC_DRIFT_DETECTED" in drift.stderr
