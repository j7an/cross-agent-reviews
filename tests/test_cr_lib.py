"""Tests for the shared helper module used by every cr_*.py script."""

import re
from pathlib import Path

import _cr_lib as lib
import pytest

# --- derive_slug ---


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/specs/2026-05-07-issue-1-design.md", "2026-05-07-issue-1"),
        ("docs/specs/auth-rewrite-spec.md", "auth-rewrite"),
        ("docs/plans/migration-plan.md", "migration"),
        ("docs/specs/2026-05-07-foo.md", "2026-05-07-foo"),
        (
            "docs/specs/2026-05-07-design-system-overhaul-design.md",
            "2026-05-07-design-system-overhaul",
        ),
        ("/abs/path/to/foo-DESIGN.md", "foo"),  # case-insensitive suffix strip
        ("foo-specification.md", "foo"),
        ("foo.md", "foo"),
    ],
)
def test_derive_slug(path, expected):
    assert lib.derive_slug(Path(path)) == expected


def test_derive_slug_does_not_strip_unhyphenated_suffix():
    # "design" embedded in slug, not preceded by hyphen — keep
    assert lib.derive_slug(Path("designsystem.md")) == "designsystem"


# --- compute_content_hash ---


def test_compute_content_hash_sha256_format(tmp_path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"hello\n")
    h = lib.compute_content_hash(f)
    assert h.startswith("sha256:")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", h)


def test_compute_content_hash_known_value(tmp_path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"hello\n")
    assert (
        lib.compute_content_hash(f)
        == "sha256:5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    )


# --- now_iso8601_utc ---


def test_now_iso8601_utc_format():
    s = lib.now_iso8601_utc()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s)


# --- atomic_write ---


def test_atomic_write_creates_file(tmp_path):
    target = tmp_path / "out.json"
    lib.atomic_write(target, '{"a": 1}\n')
    assert target.read_text() == '{"a": 1}\n'


def test_atomic_write_overwrites(tmp_path):
    target = tmp_path / "out.json"
    target.write_text("old")
    lib.atomic_write(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_no_temp_files_left(tmp_path):
    target = tmp_path / "out.json"
    lib.atomic_write(target, "x")
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("out.json.tmp")]
    assert leftovers == []


# --- find_repo_root ---


def test_find_repo_root_from_within_repo(repo_root):
    assert lib.find_repo_root(repo_root / "scripts") == repo_root


def test_find_repo_root_from_non_git_dir_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # tmp_path is not a git repo; expect fallback
    assert lib.find_repo_root(tmp_path) == tmp_path


# --- state_dir / schema_dir ---


def test_state_dir(repo_root):
    assert lib.state_dir(repo_root) == repo_root / ".cross-agent-reviews"


def test_schema_dir(repo_root):
    assert (
        lib.schema_dir(repo_root) == repo_root / "plugin" / "skills" / "cr" / "_shared" / "schema"
    )


# --- load_schema ---


def test_load_schema_returns_dict(repo_root):
    schema = lib.load_schema(repo_root, "finding.schema.json")
    assert schema["$id"] == "https://j7an.github.io/cross-agent-reviews/schema/v1/finding.json"


def test_load_schema_unknown_raises(repo_root):
    with pytest.raises(FileNotFoundError):
        lib.load_schema(repo_root, "nonexistent.schema.json")


# --- build_registry ---


def test_build_registry_resolves_finding_ref(repo_root):
    registry = lib.build_registry(repo_root)
    finding_uri = "https://j7an.github.io/cross-agent-reviews/schema/v1/finding.json"
    resolved = registry.resolver().lookup(finding_uri)
    assert resolved.contents["title"] == "Finding"


# --- canonical_json ---


def test_canonical_json_sorts_keys():
    out = lib.canonical_json({"b": 1, "a": 2})
    # sort_keys=True ⇒ "a" comes before "b"
    assert out.index('"a"') < out.index('"b"')


def test_canonical_json_indent_2():
    out = lib.canonical_json({"a": [1, 2]})
    assert "\n  " in out
