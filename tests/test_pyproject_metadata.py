"""Lock in the virtual-project decision (spec §3.1).

A future contributor adding a [build-system] block "to fix" the missing
build backend would break this test with a clear failure message.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_declares_virtual_project() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data.get("tool", {}).get("uv", {}).get("package") is False, (
        "[tool.uv].package must be False to declare virtual-project status"
    )


def test_uv_sync_locked_succeeds_in_isolated_env(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(tmp_path / "venv")
    result = subprocess.run(
        ["uv", "sync", "--locked", "--all-groups"],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"uv sync --locked failed:\n{result.stderr}"


def test_isolated_env_does_not_install_cross_agent_reviews(tmp_path: Path) -> None:
    """Virtual-project invariant: `uv sync` must NOT install our own code."""
    env = os.environ.copy()
    venv = tmp_path / "venv"
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    subprocess.run(
        ["uv", "sync", "--locked", "--all-groups"],
        env=env,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    # Inspect the isolated venv directly (don't rely on the parent's
    # importlib.metadata, which sees this project at the workspace root).
    # NB: `try` is a compound statement — it cannot follow `;` on a simple-
    # stmt line. Use real newlines and an indented suite so `python -c` parses.
    probe = (
        "import importlib.metadata as m\n"
        "import sys\n"
        "try:\n"
        "    m.version('cross-agent-reviews')\n"
        "    sys.exit(1)\n"
        "except m.PackageNotFoundError:\n"
        "    sys.exit(0)\n"
    )
    py = venv / ("Scripts" if os.name == "nt" else "bin") / "python"
    # Run with cwd outside the repo and -I (isolated mode) so Python does
    # not prepend repo-root onto sys.path; otherwise importlib.metadata
    # would discover repo-root cross_agent_reviews.egg-info/ if present
    # and falsely report the package as installed in the venv.
    result = subprocess.run(
        [str(py), "-I", "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "cross-agent-reviews is installed in the isolated venv — virtual-project "
        "invariant broken (likely a [build-system] block was added)"
    )


def test_pyright_policy_is_explicit() -> None:
    """Issue #18: [tool.pyright] must declare an explicit, documented policy.

    `include` is the scoping mechanism; a custom `exclude` is intentionally
    absent (setting one would replace Pyright's default excludes).
    """
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pyright = data.get("tool", {}).get("pyright", {})

    assert pyright.get("typeCheckingMode") == "standard", (
        "[tool.pyright].typeCheckingMode must be explicitly 'standard'"
    )
    assert pyright.get("include") == [
        "plugin/skills/cr/_helpers",
        "tests",
        "sitecustomize.py",
    ], "[tool.pyright].include must scope analysis to repo-owned Python"
    assert "exclude" not in pyright, (
        "[tool.pyright] must NOT set a custom exclude — scoping is done via "
        "include; a custom exclude would replace Pyright's default excludes"
    )
    # Preserved settings (script-mode imports, venv resolution, language floor).
    assert pyright.get("extraPaths") == ["plugin/skills/cr/_helpers"]
    assert pyright.get("pythonVersion") == "3.11"
    assert pyright.get("venvPath") == "."
    assert pyright.get("venv") == ".venv"
