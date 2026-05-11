"""Tests for the TDD-evidence audit script."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "tests" / "auditing" / "check_test_first_order.py"


def run(args, cwd):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def tdd_repo(tmp_path):
    """Create a tiny repo where test_foo.py was committed BEFORE foo.py."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "tester@example.com"], cwd=repo)
    _git(["config", "user.name", "Tester"], cwd=repo)
    (repo / "tests").mkdir()
    (repo / "scripts").mkdir()
    (repo / "tests" / "test_foo.py").write_text("def test_x(): assert True\n")
    _git(["add", "tests/test_foo.py"], cwd=repo)
    _git(["commit", "-m", "test"], cwd=repo)
    (repo / "scripts" / "foo.py").write_text("print('hello')\n")
    _git(["add", "scripts/foo.py"], cwd=repo)
    _git(["commit", "-m", "feat"], cwd=repo)
    return repo


@pytest.fixture
def non_tdd_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "tester@example.com"], cwd=repo)
    _git(["config", "user.name", "Tester"], cwd=repo)
    (repo / "tests").mkdir()
    (repo / "scripts").mkdir()
    (repo / "scripts" / "foo.py").write_text("print('hello')\n")
    _git(["add", "scripts/foo.py"], cwd=repo)
    _git(["commit", "-m", "feat"], cwd=repo)
    (repo / "tests" / "test_foo.py").write_text("def test_x(): assert True\n")
    _git(["add", "tests/test_foo.py"], cwd=repo)
    _git(["commit", "-m", "test"], cwd=repo)
    return repo


def test_passes_when_tests_first(tdd_repo):
    result = run(["--pair", "tests/test_foo.py:scripts/foo.py"], cwd=tdd_repo)
    assert result.returncode == 0, result.stderr
    assert "All test-first orderings hold." in result.stdout


def test_fails_when_implementation_first(non_tdd_repo):
    result = run(["--pair", "tests/test_foo.py:scripts/foo.py"], cwd=non_tdd_repo)
    assert result.returncode == 1
    assert "is not strictly earlier than" in result.stderr


@pytest.fixture
def same_commit_repo(tmp_path):
    """Repo where test_foo.py and foo.py are added in the SAME commit. The
    audit must reject this — same-commit is not TDD evidence."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "tester@example.com"], cwd=repo)
    _git(["config", "user.name", "Tester"], cwd=repo)
    (repo / "tests").mkdir()
    (repo / "scripts").mkdir()
    (repo / "tests" / "test_foo.py").write_text("def test_x(): assert True\n")
    (repo / "scripts" / "foo.py").write_text("print('hello')\n")
    _git(["add", "tests/test_foo.py", "scripts/foo.py"], cwd=repo)
    _git(["commit", "-m", "feat: foo + tests"], cwd=repo)
    return repo


def test_fails_when_test_and_impl_in_same_commit(same_commit_repo):
    result = run(["--pair", "tests/test_foo.py:scripts/foo.py"], cwd=same_commit_repo)
    assert result.returncode == 1
    assert "committed together" in result.stderr or "is not strictly earlier" in result.stderr


@pytest.fixture
def retrofit_repo(tmp_path):
    """Repo where a script existed at tag `v0.0.0`, was modified later, and
    the characterization test was committed BEFORE that modification — the
    retrofit-evidence rule (§8.3 of the design)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "tester@example.com"], cwd=repo)
    _git(["config", "user.name", "Tester"], cwd=repo)
    (repo / "tests" / "bats").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "verify.sh").write_text("#!/bin/bash\necho v0\n")
    _git(["add", "scripts/verify.sh"], cwd=repo)
    _git(["commit", "-m", "feat: initial verify.sh"], cwd=repo)
    _git(["tag", "v0.0.0"], cwd=repo)
    # Characterization test BEFORE the modification.
    (repo / "tests" / "bats" / "test_verify.bats").write_text("@test 'works' { run true; }\n")
    _git(["add", "tests/bats/test_verify.bats"], cwd=repo)
    _git(["commit", "-m", "test: characterize verify.sh"], cwd=repo)
    # Then modify the script.
    (repo / "scripts" / "verify.sh").write_text("#!/bin/bash\necho v1\n")
    _git(["add", "scripts/verify.sh"], cwd=repo)
    _git(["commit", "-m", "feat: extend verify.sh"], cwd=repo)
    return repo


@pytest.fixture
def retrofit_violation_repo(tmp_path):
    """Same shape as `retrofit_repo` but the script is modified BEFORE the
    characterization test — violating the retrofit rule."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "tester@example.com"], cwd=repo)
    _git(["config", "user.name", "Tester"], cwd=repo)
    (repo / "tests" / "bats").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "verify.sh").write_text("#!/bin/bash\necho v0\n")
    _git(["add", "scripts/verify.sh"], cwd=repo)
    _git(["commit", "-m", "feat: initial verify.sh"], cwd=repo)
    _git(["tag", "v0.0.0"], cwd=repo)
    # Modify FIRST.
    (repo / "scripts" / "verify.sh").write_text("#!/bin/bash\necho v1\n")
    _git(["add", "scripts/verify.sh"], cwd=repo)
    _git(["commit", "-m", "feat: extend verify.sh"], cwd=repo)
    # Then add characterization test (too late).
    (repo / "tests" / "bats" / "test_verify.bats").write_text("@test 'works' { run true; }\n")
    _git(["add", "tests/bats/test_verify.bats"], cwd=repo)
    _git(["commit", "-m", "test: characterize verify.sh"], cwd=repo)
    return repo


def test_retrofit_passes_when_characterization_first(retrofit_repo):
    result = run(
        ["--retrofit", "tests/bats/test_verify.bats:scripts/verify.sh:v0.0.0"], cwd=retrofit_repo
    )
    assert result.returncode == 0, result.stderr
    assert "All test-first orderings hold." in result.stdout


def test_retrofit_fails_when_script_modified_before_characterization(retrofit_violation_repo):
    result = run(
        ["--retrofit", "tests/bats/test_verify.bats:scripts/verify.sh:v0.0.0"],
        cwd=retrofit_violation_repo,
    )
    assert result.returncode == 1
    assert "retrofit" in result.stderr.lower() or "is not strictly after" in result.stderr.lower()
