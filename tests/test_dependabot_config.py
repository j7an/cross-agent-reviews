"""Validate .github/dependabot.yml — especially composite-action coverage.

Closes the gap filed at j7an/nexus-mcp#189: directory: "/" does NOT recurse
into .github/actions/*/action.yml, so each composite action directory must
appear explicitly in the github-actions ecosystem's `directories:` list.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPENDABOT_PATH = REPO_ROOT / ".github" / "dependabot.yml"


@pytest.fixture(scope="module")
def config() -> dict:
    assert DEPENDABOT_PATH.exists(), f"missing: {DEPENDABOT_PATH}"
    return yaml.safe_load(DEPENDABOT_PATH.read_text(encoding="utf-8"))


def test_config_version_is_2(config: dict) -> None:
    assert config["version"] == 2


def test_has_two_ecosystems(config: dict) -> None:
    ecosystems = sorted(e["package-ecosystem"] for e in config["updates"])
    assert ecosystems == ["github-actions", "uv"]


def test_github_actions_covers_every_composite_action(config: dict) -> None:
    gh_actions = next(e for e in config["updates"] if e["package-ecosystem"] == "github-actions")
    directories = gh_actions.get("directories") or [gh_actions.get("directory", "/")]
    composite_dirs = [
        "/" + str(p.parent.relative_to(REPO_ROOT)).replace("\\", "/")
        for p in (REPO_ROOT / ".github" / "actions").glob("*/action.yml")
    ]
    for cd in composite_dirs:
        assert cd in directories, (
            f"Composite action dir {cd} not covered by directories: {directories}"
        )


def test_uv_ecosystem_ignores_semver_major(config: dict) -> None:
    uv = next(e for e in config["updates"] if e["package-ecosystem"] == "uv")
    ignore = uv.get("ignore", [])
    assert any(
        i.get("dependency-name") == "*"
        and "version-update:semver-major" in i.get("update-types", [])
        for i in ignore
    ), "uv ecosystem must ignore semver-major updates (spec §7.3)"


def test_github_actions_ecosystem_does_not_ignore_semver_major(config: dict) -> None:
    """Spec §7.3: major-version ignore is scoped to uv only."""
    gh = next(e for e in config["updates"] if e["package-ecosystem"] == "github-actions")
    ignore = gh.get("ignore", [])
    has_major_ignore = any(
        "version-update:semver-major" in i.get("update-types", []) for i in ignore
    )
    assert not has_major_ignore, "github-actions ecosystem should NOT ignore majors (spec §7.3)"


def test_both_ecosystems_have_cooldown_7_days(config: dict) -> None:
    for ecosystem in config["updates"]:
        cooldown = ecosystem.get("cooldown", {})
        assert cooldown.get("default-days") == 7, (
            f"{ecosystem['package-ecosystem']} missing cooldown.default-days: 7"
        )
