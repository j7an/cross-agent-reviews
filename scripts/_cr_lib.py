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
    base = artifact_path.name
    if base.endswith(".md"):
        base = base[:-3]
    return _SUFFIX_RE.sub("", base)


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


def schema_dir(repo_root: Path) -> Path:
    return repo_root / "plugin" / "skills" / "cr" / "_shared" / "schema"


def load_schema(repo_root: Path, name: str) -> dict:
    return json.loads((schema_dir(repo_root) / name).read_text())


def build_registry(repo_root: Path) -> Registry:
    resources = []
    for name in SCHEMA_FILES:
        schema = load_schema(repo_root, name)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def canonical_json(obj: object) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"
