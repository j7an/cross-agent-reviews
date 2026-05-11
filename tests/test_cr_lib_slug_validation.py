"""Tests for strict slug validation in derive_slug + the CLI mains.

A reviewer demonstrated three slug-derivation bugs:

    input=...md   -> slug='..'   (path escape: writes
                                  .cross-agent-reviews/../state.json,
                                  i.e. the repo root)
    input=.md     -> slug=''     (empty: lands at
                                  .cross-agent-reviews/state.json,
                                  slug-less)
    input=..md    -> slug='.'    (lands at
                                  .cross-agent-reviews/state.json)

After the fix, derive_slug applies a strict allowlist regex
(`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`) to the post-strip base and raises
ValueError on no-match. The CLI mains catch the ValueError and exit 1
with a clean stderr message (no traceback)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import _cr_lib as lib
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPERS_DIR = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers"
PICK_SLUG = HELPERS_DIR / "cr_state_pick_slug.py"
INIT = HELPERS_DIR / "cr_state_init.py"
WRITE = HELPERS_DIR / "cr_state_write.py"
READ = HELPERS_DIR / "cr_state_read.py"
STATUS = HELPERS_DIR / "cr_state_status.py"


# --- derive_slug: invalid inputs raise ValueError ---


@pytest.mark.parametrize(
    "name",
    [
        "...md",  # post-strip "..": path escape
        ".md",  # post-strip "": empty
        "..md",  # post-strip ".": current-dir
        "-foo-spec.md",  # leading dash rejected
        "_foo-spec.md",  # leading underscore rejected
        ".foo-spec.md",  # leading dot rejected
        "a" * 65 + ".md",  # length > 64
    ],
)
def test_derive_slug_rejects_invalid(name: str) -> None:
    # The error message must reference the offending input (filename or
    # post-strip base) so the operator can fix it without grepping source.
    with pytest.raises(ValueError, match="invalid slug"):
        lib.derive_slug(Path(name))


def test_derive_slug_rejects_invalid_with_directory_prefix() -> None:
    # Path.name strips dirs, so the rejection only depends on the basename.
    with pytest.raises(ValueError, match="invalid slug"):
        lib.derive_slug(Path("docs/specs/...md"))


# --- derive_slug: valid inputs still produce the expected slug ---


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("foo-spec.md", "foo"),
        ("foo_bar-design.md", "foo_bar"),  # underscore in middle
        ("foo.bar-plan.md", "foo.bar"),  # dot in middle
        ("a" * 64 + ".md", "a" * 64),  # length boundary 64
    ],
)
def test_derive_slug_accepts_valid(name: str, expected: str) -> None:
    assert lib.derive_slug(Path(name)) == expected


# --- CLI: cr_state_pick_slug rejects malicious paths cleanly ---


def _run_pick_slug(input_arg: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PICK_SLUG), "--input", input_arg],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


@pytest.mark.parametrize(
    "malicious",
    ["docs/specs/...md", ".md", "..md"],
)
def test_pick_slug_rejects_malicious_path(workspace: Path, malicious: str) -> None:
    result = _run_pick_slug(malicious, cwd=workspace)
    assert result.returncode == 1, (
        f"expected exit 1 for malicious input {malicious!r}, got {result.returncode}; "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    assert "ERROR" in result.stderr
    # Clean error: no Python traceback should leak.
    assert "Traceback" not in result.stderr


def test_pick_slug_rejects_malicious_slug_name(workspace: Path) -> None:
    # A bare slug-name input that would also be path-unsafe must be rejected,
    # not silently accepted via the "treat as a new slug name" branch.
    result = _run_pick_slug("..", cwd=workspace)
    assert result.returncode == 1
    assert "ERROR" in result.stderr
    assert "Traceback" not in result.stderr


# --- CLI: cr_state_init rejects malicious artifact paths cleanly ---


@pytest.fixture
def init_workspace(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    # Plant a real file at a path whose Path.name derives to an invalid slug.
    # Using "...md" so derive_slug yields ".." (post-strip), which the regex
    # rejects.
    artifact = tmp_path / "docs" / "specs" / "...md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# placeholder spec\n")
    # link schema dir for find_repo_root + schema discovery
    schema_src = REPO_ROOT / "plugin" / "skills" / "cr" / "_shared" / "schema"
    schema_dst = tmp_path / "plugin" / "skills" / "cr" / "_shared" / "schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(schema_src, schema_dst)
    return tmp_path


def test_init_rejects_malicious_artifact_path(init_workspace: Path) -> None:
    artifact = init_workspace / "docs" / "specs" / "...md"
    result = subprocess.run(
        [
            sys.executable,
            str(INIT),
            "--artifact-path",
            str(artifact),
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        capture_output=True,
        text=True,
        cwd=init_workspace,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )
    assert result.returncode == 1, (
        f"expected exit 1; got {result.returncode}; "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    assert "ERROR" in result.stderr
    assert "Traceback" not in result.stderr
    # The slug dir must NOT have been created (no path escape).
    assert not (init_workspace / ".cross-agent-reviews").exists()


# --- CLI: cr_state_write/read/status reject malicious --slug values ---
#
# `--slug` is operator-controlled argv input, not derived from a path. Even
# with derive_slug locked down at the upstream picker, downstream helpers
# can be invoked directly with `--slug ..` and would still resolve
# `state_dir(repo_root) / args.slug` to the repo root. validate_slug must
# fire at every entry point that receives a slug from argv — defense in
# depth, not just upstream.


def _run(script: Path, extra: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *extra],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )


def test_write_rejects_malicious_slug(workspace: Path) -> None:
    # Validation must fire before any state.json or --input-file read so
    # this exits 1 from slug validation, not from a downstream missing-file
    # error. Asserting "invalid slug" in stderr (the validate_slug message)
    # is what proves the rejection is happening at the right layer.
    result = _run(
        WRITE,
        [
            "--slug",
            "..",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(workspace / "nonexistent.json"),
        ],
        cwd=workspace,
    )
    assert result.returncode == 1, (
        f"expected exit 1; got {result.returncode}; stderr={result.stderr!r}"
    )
    assert "invalid slug" in result.stderr, (
        f"expected validate_slug rejection message; got stderr={result.stderr!r}"
    )
    assert "Traceback" not in result.stderr
    assert not (workspace / ".cross-agent-reviews").exists()


def test_read_rejects_malicious_slug(workspace: Path) -> None:
    # The "no state for slug" path also exits 1 with ERROR in stderr,
    # so without "invalid slug" in the assertion this test would pass
    # coincidentally even with no validation present. The whole point of
    # this test is to prove validate_slug fires upstream of any state read.
    result = _run(READ, ["--slug", "..", "--artifact-type", "spec"], cwd=workspace)
    assert result.returncode == 1
    assert "invalid slug" in result.stderr, (
        f"expected validate_slug rejection message; got stderr={result.stderr!r}"
    )
    assert "Traceback" not in result.stderr
    assert not (workspace / ".cross-agent-reviews").exists()


def test_status_rejects_malicious_slug(workspace: Path) -> None:
    # cr_state_status accepts an optional --slug. When provided, it MUST
    # be validated even though the no-slug "list all" path is still legal.
    result = _run(STATUS, ["--slug", ".."], cwd=workspace)
    assert result.returncode == 1
    assert "invalid slug" in result.stderr, (
        f"expected validate_slug rejection message; got stderr={result.stderr!r}"
    )
    assert "Traceback" not in result.stderr
