"""Shared pytest fixtures and path constants for cross-agent-reviews tests."""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCHEMA_DIR = REPO_ROOT / "plugin" / "skills" / "cr" / "_shared" / "schema"


@pytest.fixture(autouse=True, scope="session")
def _scrub_git_env():
    # When pytest runs from a git hook (pre-push), git exports GIT_DIR and
    # GIT_INDEX_FILE pointing at the outer repo. Test fixtures that do
    # `git init` in tmp_path then leak writes into the outer repo's index
    # because GIT_INDEX_FILE wins over .git discovery from cwd.
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("GIT_")}
    try:
        yield
    finally:
        os.environ.update(saved)


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def schema_dir() -> Path:
    return SCHEMA_DIR
