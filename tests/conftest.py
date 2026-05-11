"""Shared pytest fixtures and path constants for cross-agent-reviews tests."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SCHEMA_DIR = REPO_ROOT / "plugin" / "skills" / "cr" / "_shared" / "schema"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def schema_dir() -> Path:
    return SCHEMA_DIR
