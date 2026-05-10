"""Shared helpers used by every cr_*.py script.

Single source of truth for slug derivation, content hashing, ISO 8601 UTC
timestamps, atomic file writes, repo-root resolution, schema-directory
location, and JSON Schema registry construction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from referencing import Registry, Resource

_SUFFIX_RE = re.compile(r"-(?:design|spec|plan|specification)$", re.IGNORECASE)
# Strict allowlist applied AFTER suffix-stripping in derive_slug. Also used by
# `validate_slug` for slug-name input that does NOT pass through derive_slug
# (e.g. a bare slug typed at the CLI). Constraints:
#   - first char alnum (rejects leading `.`, `_`, `-` — esp. `..`/`.` which
#     would resolve as parent/current dir under state_dir)
#   - subsequent chars (0..63) alnum or `.`, `_`, `-`
#   - total length 1..64
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

SCHEMA_FILES = (
    "finding.schema.json",
    "verification.schema.json",
    "adjudication.schema.json",
    "changelog-entry.schema.json",
    "self-review-entry.schema.json",
    "state.schema.json",
    "round-audit.schema.json",
    "round-settle.schema.json",
)


def derive_slug(artifact_path: Path) -> str:
    """Derive a filesystem-safe slug from an artifact path.

    Strips the `.md` extension and any `-design/-spec/-plan/-specification`
    suffix (case-insensitive), then enforces the `_SLUG_RE` allowlist.

    Raises:
        ValueError: when the post-strip base does not match `_SLUG_RE`.
            The message names both `artifact_path.name` and the offending
            base so the operator can fix the input without reading source.
            This guards against path-escape inputs like `...md` (post-strip
            base `..`), `.md` (empty base), and `..md` (base `.`), all of
            which would resolve to or above the state directory if used as
            a slug.
    """
    base = artifact_path.name
    if base.endswith(".md"):
        base = base[:-3]
    base = _SUFFIX_RE.sub("", base)
    if _SLUG_RE.fullmatch(base) is None:
        raise ValueError(
            f"invalid slug derived from {artifact_path.name!r}: "
            f"{base!r} does not match [A-Za-z0-9][A-Za-z0-9._-]{{0,63}}"
        )
    return base


def validate_slug(slug: str) -> None:
    """Validate a slug-name input that does not pass through derive_slug.

    Used by `cr_state_pick_slug` for the slug-name branch (operator types a
    bare slug rather than an artifact path). Mirrors the regex enforced by
    derive_slug so both entry points share a single source of truth.

    Raises:
        ValueError: when `slug` does not match `_SLUG_RE`.
    """
    if _SLUG_RE.fullmatch(slug) is None:
        raise ValueError(f"invalid slug {slug!r}: does not match [A-Za-z0-9][A-Za-z0-9._-]{{0,63}}")


def compute_content_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def now_iso8601_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}")
    tmp.write_text(content)
    os.replace(tmp, path)


def find_repo_root(start: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            check=True,
            capture_output=True,
            text=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return start.resolve()


def state_dir(repo_root: Path) -> Path:
    return repo_root / ".cross-agent-reviews"


def schema_dir() -> Path:
    """Self-locating: schemas are siblings of this _helpers/ dir.

    Schemas live next to this file at `<plugin_root>/skills/cr/_shared/schema/`,
    not under the operator's repo. Resolving from `__file__` lets the plugin
    work whether the operator's CWD is a repo root, a subdirectory, or
    somewhere entirely outside any repo.
    """
    return Path(__file__).resolve().parent.parent / "_shared" / "schema"


def load_schema(name: str) -> dict:
    return json.loads((schema_dir() / name).read_text())


def build_registry() -> Registry:
    resources = []
    for name in SCHEMA_FILES:
        schema = load_schema(name)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def canonical_json(obj: object) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"
