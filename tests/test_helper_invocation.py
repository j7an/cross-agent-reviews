"""Regression test: every CLI helper must be invocable from the plugin path.

The helpers live at `plugin/skills/cr/_helpers/cr_*.py` and are launched
in script mode (no package import). This test confirms two forms exit 0
and print argparse's "usage:" line:

1. Direct: `python plugin/skills/cr/_helpers/cr_X.py --help` — proves
   the underlying helper scripts work in isolation.
2. Wrapper: `plugin/skills/cr/_helpers/cr <subcommand> --help` — proves
   the uv-backed shell wrapper correctly maps subcommands to helpers
   and that `uv run --python ">=3.11" --with jsonschema --with referencing`
   provisions a working runtime. The wrapper is the documented form in
   SKILL.md / rounds/*.md / _shared/*.md.

Failing on the direct form means a helper's argparse interface
regressed; failing on the wrapper form means the wrapper script is
missing, broken, or its subcommand map drifted from the helper file
names.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPERS_DIR = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers"
WRAPPER = HELPERS_DIR / "cr"

HELPERS = (
    "cr_state_init.py",
    "cr_state_read.py",
    "cr_state_write.py",
    "cr_state_pick_slug.py",
    "cr_state_status.py",
    "cr_validate.py",
    "cr_validate_finding.py",
    "cr_extract_placeholders.py",
)

# Subcommand <-> helper script mapping documented in the wrapper header.
# Lives here as a tuple-of-tuples (not a dict) so the parametrize id is
# stable and human-readable.
WRAPPER_SUBCOMMANDS = (
    ("state-init", "cr_state_init.py"),
    ("state-read", "cr_state_read.py"),
    ("state-write", "cr_state_write.py"),
    ("state-pick-slug", "cr_state_pick_slug.py"),
    ("state-status", "cr_state_status.py"),
    ("validate", "cr_validate.py"),
    ("validate-finding", "cr_validate_finding.py"),
    ("extract-placeholders", "cr_extract_placeholders.py"),
)


@pytest.mark.parametrize("helper", HELPERS)
def test_helper_invokable_from_plugin_path(helper: str) -> None:
    script = HELPERS_DIR / helper
    assert script.exists(), f"missing helper: {script}"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ},
        check=False,
    )
    assert result.returncode == 0, (
        f"{helper} --help exited {result.returncode}; stderr={result.stderr}"
    )
    assert "usage:" in result.stdout, (
        f"{helper} --help did not print 'usage:' line; stdout={result.stdout!r}"
    )


@pytest.mark.parametrize(("subcommand", "script_name"), WRAPPER_SUBCOMMANDS)
def test_wrapper_invokes_helper(subcommand: str, script_name: str) -> None:
    """Invoke each subcommand via the uv-backed wrapper.

    `script_name` is captured in the parametrize id so a failure points
    at which helper's mapping is broken; the wrapper itself does the
    name resolution.
    """
    assert WRAPPER.exists(), f"missing wrapper: {WRAPPER}"
    assert os.access(WRAPPER, os.X_OK), f"wrapper not executable: {WRAPPER}"
    result = subprocess.run(
        [str(WRAPPER), subcommand, "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ},
        check=False,
    )
    assert result.returncode == 0, (
        f"cr {subcommand} --help exited {result.returncode}; stderr={result.stderr}; "
        f"expected to delegate to {script_name}"
    )
    assert "usage:" in result.stdout, (
        f"cr {subcommand} --help did not print 'usage:' line; stdout={result.stdout!r}"
    )


def test_wrapper_no_args_exits_2() -> None:
    """No subcommand exits 2 with 'Usage:' on stderr."""
    assert WRAPPER.exists(), f"missing wrapper: {WRAPPER}"
    result = subprocess.run(
        [str(WRAPPER)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ},
        check=False,
    )
    assert result.returncode == 2, (
        f"cr (no args) exited {result.returncode}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert "Usage:" in result.stderr, (
        f"cr (no args) did not print 'Usage:' to stderr; stderr={result.stderr!r}"
    )


def test_wrapper_unknown_subcommand_exits_2() -> None:
    """Unknown subcommand exits 2 with 'unknown subcommand' on stderr."""
    assert WRAPPER.exists(), f"missing wrapper: {WRAPPER}"
    result = subprocess.run(
        [str(WRAPPER), "definitely-not-a-subcommand"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ},
        check=False,
    )
    assert result.returncode == 2, (
        f"cr <bogus> exited {result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert "unknown subcommand" in result.stderr, (
        f"cr <bogus> did not print 'unknown subcommand' to stderr; stderr={result.stderr!r}"
    )
