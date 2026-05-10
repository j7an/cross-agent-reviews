#!/usr/bin/env python3
"""Render a human-readable timeline view of state across slugs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from _cr_lib import find_repo_root, state_dir, validate_slug

ROUND_STAGES = ("1a", "1b", "2a", "2b", "3a", "3b")


def _humanize_age(then_iso: str, now: datetime) -> str:
    then = datetime.strptime(then_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    diff = now - then
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h{m}m ago"
    return f"{seconds // 86400}d ago"


def _render_block(art: str, block: dict, artifact_dir: Path, now: datetime) -> list[str]:
    lines = [f"  {art.capitalize():<5} ({block['path']})"]
    completed = set(block["completed_rounds"])
    current = block["current_stage"]
    for stage in ROUND_STAGES:
        if stage in completed:
            rp = artifact_dir / f"round-{stage}.json"
            if rp.exists():
                emitted = json.loads(rp.read_text())["emitted_at"]
                lines.append(
                    f"    {stage:<3}  completed  {emitted}   ({_humanize_age(emitted, now)})"
                )
            else:
                lines.append(f"    {stage:<3}  completed  (round file missing — pending import)")
        elif current == f"round_{stage}_pending":
            lines.append(f"    {stage:<3}  PENDING")
        else:
            lines.append(f"    {stage:<3}  —")
    return lines


def _integrity_for(state: dict, slug_dir: Path) -> str:
    for art in ("spec", "plan"):
        block = state.get(art)
        if block is None:
            continue
        artifact_dir = slug_dir / art
        max_emitted = ""
        for stage in block["completed_rounds"]:
            rp = artifact_dir / f"round-{stage}.json"
            if not rp.exists():
                continue
            emitted = json.loads(rp.read_text())["emitted_at"]
            if emitted > max_emitted:
                max_emitted = emitted
        if max_emitted and block["last_updated_at"] < max_emitted:
            return "STATE_INTEGRITY_ERROR"
    return "OK"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--slug")
    args = p.parse_args()
    if args.slug is not None:
        try:
            validate_slug(args.slug)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    repo_root = find_repo_root(Path.cwd())
    state_root = state_dir(repo_root)
    if not state_root.exists():
        print("No active slugs.")
        return 0
    slugs = sorted(state_root.iterdir()) if args.slug is None else [state_root / args.slug]
    now = datetime.now(UTC)
    for slug_dir in slugs:
        sp = slug_dir / "state.json"
        if not sp.is_file():
            continue
        state = json.loads(sp.read_text())
        print(f"Slug: {state['slug']}")
        for art in ("spec", "plan"):
            block = state.get(art)
            if block is None:
                print(f"  {art.capitalize():<5} [not yet started]")
                continue
            for line in _render_block(art, block, slug_dir / art, now):
                print(line)
        print()
        print(
            f"State integrity:  {_integrity_for(state, slug_dir)}  (state.json ↔ round emitted_at)"
        )
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
