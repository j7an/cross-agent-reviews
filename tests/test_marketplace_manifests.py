"""Assert version sync across the 4 version-bearing JSON manifests.

The 4 manifests:
  - .claude-plugin/marketplace.json       (.plugins[0].version)
  - .codex-plugin/marketplace.json        (.plugins[0].version)
  - plugin/.claude-plugin/plugin.json     (.version)
  - plugin/.codex-plugin/plugin.json      (.version)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

MARKETPLACE_PATHS = [
    REPO_ROOT / ".claude-plugin" / "marketplace.json",
    REPO_ROOT / ".codex-plugin" / "marketplace.json",
]
PLUGIN_PATHS = [
    REPO_ROOT / "plugin" / ".claude-plugin" / "plugin.json",
    REPO_ROOT / "plugin" / ".codex-plugin" / "plugin.json",
]
ALL_PATHS = MARKETPLACE_PATHS + PLUGIN_PATHS


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", ALL_PATHS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_manifest_parses(path: Path) -> None:
    assert path.exists(), f"missing manifest: {path}"
    _load(path)


def test_all_four_versions_agree() -> None:
    versions: dict[str, str] = {}
    for path in MARKETPLACE_PATHS:
        versions[str(path.relative_to(REPO_ROOT))] = _load(path)["plugins"][0]["version"]
    for path in PLUGIN_PATHS:
        versions[str(path.relative_to(REPO_ROOT))] = _load(path)["version"]
    distinct = set(versions.values())
    assert len(distinct) == 1, f"version drift across manifests: {versions}"


@pytest.mark.parametrize("path", MARKETPLACE_PATHS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_marketplace_source_is_plugin_dir(path: Path) -> None:
    # Scoped to the two marketplace files only — plugin.json files
    # have no plugins[] array (spec §8.1).
    assert _load(path)["plugins"][0]["source"] == "./plugin"
