#!/usr/bin/env python3
"""Initialize state for a new cross-agent-reviews pipeline run.

Derives the slug from the artifact path (§5.5), creates
.cross-agent-reviews/<slug>/, hashes the artifact, writes the initial
state.json, applies the slug-collision policy (§11.3), and prompts to
add `.cross-agent-reviews/` to `.gitignore` if absent.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from scripts._cr_lib import (
    atomic_write,
    canonical_json,
    compute_content_hash,
    derive_slug,
    find_repo_root,
    now_iso8601_utc,
    state_dir,
)


def _confirm(prompt: str) -> bool:
    sys.stderr.write(prompt)
    sys.stderr.flush()
    answer = sys.stdin.readline().strip().lower()
    return answer in {"y", "yes"}


def _gitignore_check(repo_root: Path, prompt: bool) -> None:
    gi = repo_root / ".gitignore"
    needle = ".cross-agent-reviews/"
    if gi.exists() and needle in gi.read_text():
        return
    if not prompt:
        return
    if _confirm(f"Append `{needle}` to .gitignore? [y/N] "):
        existing = gi.read_text() if gi.exists() else ""
        with gi.open("a") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(needle + "\n")


def _archive_old(slug_dir: Path, artifact_type: str) -> None:
    timestamp = now_iso8601_utc().replace(":", "")  # safe in filenames
    archive_root = slug_dir / f".archive-{timestamp}"
    archive_root.mkdir(parents=True, exist_ok=True)
    src = slug_dir / artifact_type
    if src.exists():
        shutil.move(str(src), str(archive_root / artifact_type))


def _new_artifact_block(
    stored_path: Path,
    *,
    content_hash: str,
    artifact_type: str,
    spec_hash: str | None,
) -> dict:
    """Build a fresh state block.

    `stored_path` is the (typically repo-relative) path persisted to state;
    `content_hash` is computed by the caller against the resolved absolute
    artifact path so initialization works from any working directory inside
    the repo. Mixing them up would make `compute_content_hash` interpret a
    repo-relative path against `Path.cwd()` and fail (or hash a different
    file) when the operator runs `cr_state_init` from a subdirectory.
    """
    now = now_iso8601_utc()
    block: dict = {
        "path": str(stored_path),
        "content_hash": content_hash,
        "current_stage": "round_1a_pending",
        "completed_rounds": [],
        "started_at": now,
        "last_updated_at": now,
    }
    if artifact_type == "plan" and spec_hash is not None:
        block["spec_hash_at_start"] = spec_hash
    return block


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", required=True, type=Path)
    parser.add_argument("--artifact-type", choices=["spec", "plan"], required=True)
    parser.add_argument("--no-gitignore-prompt", action="store_true")
    args = parser.parse_args()

    artifact = args.artifact_path
    if not artifact.is_absolute():
        artifact = (Path.cwd() / artifact).resolve()
    if not artifact.is_file():
        print(f"ERROR: artifact path not found: {artifact}", file=sys.stderr)
        return 2

    repo_root = find_repo_root(artifact.parent)

    rel_artifact = (
        artifact.relative_to(repo_root) if artifact.is_relative_to(repo_root) else artifact
    )
    slug = derive_slug(artifact)
    # Hash against the resolved absolute path so the read works regardless
    # of which directory the operator invoked the script from. The relative
    # path is what we persist (so state.json is portable across hosts), but
    # the bytes-on-disk are what we hash.
    content_hash = compute_content_hash(artifact)

    state_root = state_dir(repo_root)
    slug_dir = state_root / slug
    state_path = slug_dir / "state.json"
    # NOTE: defer slug_dir.mkdir until after every refusal/confirmation path
    # below has cleared. Creating it eagerly leaves an empty `<slug>/` directory
    # behind when the operator declines the plan-only confirmation (§11.3) or
    # when a spec-block addition is rejected for ordering — which the
    # `test_plan_only_warns_and_requires_confirmation` contract forbids.

    state: dict
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:
        state = {"schema_version": 1, "slug": slug}

    block_key = args.artifact_type
    existing = state.get(block_key)

    if existing is None:
        if block_key == "plan":
            spec_block = state.get("spec")
            if (
                spec_block is not None
                and spec_block.get("current_stage") != "ready_for_implementation"
            ):
                print(
                    "ERROR: spec review must be terminal before a plan review can begin (§11.3).",
                    file=sys.stderr,
                )
                return 1
            spec_hash = spec_block["content_hash"] if spec_block is not None else None
            if spec_hash is None:
                # plan-only init — warn and confirm
                warning = (
                    "WARNING: Plan-only review: cross-artifact placeholder check is disabled. "
                    "Hallucinated literal substitutions for spec placeholders will not be "
                    "detected. Recommended: review the spec first under the same slug, then "
                    "re-run plan init.\nProceed with plan-only review? [y/N] "
                )
                if not _confirm(warning):
                    return 1
            state[block_key] = _new_artifact_block(
                rel_artifact,
                content_hash=content_hash,
                artifact_type="plan",
                spec_hash=spec_hash,
            )
        else:
            # Adding a spec block to a slug that already has a plan block would
            # leave `state.plan.spec_hash_at_start` absent — violating the
            # script-level invariant (§6.1) that the anchor is present whenever
            # both blocks exist, and silently passing every later drift check.
            # The §11.3 ordering rule is "spec first, then plan"; reversing it
            # is not supported in v0.1.x. The operator must either start a new
            # slug for the spec or manually archive the plan block first.
            if state.get("plan") is not None:
                print(
                    "ERROR: cannot initialise a spec block on a slug that already has a plan block "
                    "(§11.3 mandates spec-first ordering). Use a new slug for the spec, or archive "
                    "the existing plan block manually before re-running spec init.",
                    file=sys.stderr,
                )
                return 1
            state[block_key] = _new_artifact_block(
                rel_artifact,
                content_hash=content_hash,
                artifact_type="spec",
                spec_hash=None,
            )
    else:
        if existing.get("current_stage") == "ready_for_implementation":
            if not _confirm(
                f"State block for `{block_key}` is terminal. Archive and start fresh? [y/N] "
            ):
                return 1
            _archive_old(slug_dir, block_key)
            spec_hash = state.get("spec", {}).get("content_hash") if block_key == "plan" else None
            state[block_key] = _new_artifact_block(
                rel_artifact,
                content_hash=content_hash,
                artifact_type=block_key,
                spec_hash=spec_hash,
            )
        else:
            print(
                f"ERROR: state block for `{block_key}` is in-flight ({existing['current_stage']}).",
                file=sys.stderr,
            )
            return 1

    if not args.no_gitignore_prompt:
        _gitignore_check(repo_root, prompt=True)

    slug_dir.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(state)
    atomic_write(state_path, payload)
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
