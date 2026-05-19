"""Validate local hook cost stays bounded while CI keeps full coverage."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _local_hook(config: dict, hook_id: str) -> dict:
    local_repo = next(repo for repo in config["repos"] if repo["repo"] == "local")
    return next(hook for hook in local_repo["hooks"] if hook["id"] == hook_id)


def test_pre_push_pytest_hook_is_smoke_not_full_coverage() -> None:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    hook = _local_hook(config, "pytest")
    entry = hook["entry"]

    assert hook["stages"] == ["pre-push"]
    assert hook["always_run"] is True
    assert hook["pass_filenames"] is False
    assert "--cov" not in entry
    assert "tests/test_smoke.py" in entry
    assert "tests/test_cr_lib.py" in entry
    assert "tests/test_helper_invocation.py" in entry


def test_ci_keeps_full_coverage_gate() -> None:
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "uv run pytest --cov=plugin/skills/cr/_helpers tests/" in ci


def test_pre_push_bats_hook_is_smoke_not_full_suite() -> None:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    hook = _local_hook(config, "bats")
    entry = hook["entry"]

    assert hook["stages"] == ["pre-push"]
    assert hook["always_run"] is True
    assert hook["pass_filenames"] is False
    assert entry.startswith("uv run bats ")
    assert entry != "bats tests/bats/"
    assert entry != "uv run bats tests/bats/"
    assert "tests/bats/test_cr_wrapper.bats" in entry
    assert "tests/bats/test_release_archive_config.bats" in entry
    assert "tests/bats/test_version_bump_config.bats" in entry


def test_ci_keeps_full_bats_suite() -> None:
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "bats tests/bats/" in ci
