"""Regression test: every CLI helper must be invocable from the plugin path.

The helpers live at `plugin/skills/cr/_helpers/cr_*.py` and are launched
in script mode (no package import). This test confirms the documented
invocation form (`python plugin/skills/cr/_helpers/cr_X.py --help`)
exits 0 and prints argparse's "usage:" line.

Failing on this test today means the move documented in the F1 task has
not been performed yet (red phase of TDD).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPERS_DIR = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers"

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
