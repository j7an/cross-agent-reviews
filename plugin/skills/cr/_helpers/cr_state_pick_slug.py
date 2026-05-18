#!/usr/bin/env python3
"""Resolve which slug to advance, given operator input + filesystem state."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _cr_lib import (
    _SLUG_RE,
    canonical_json,
    derive_slug,
    find_repo_root,
    state_dir,
    validate_slug,
)

ROUND_STAGES = ("1a", "1b", "2a", "2b", "3a", "3b")

MODE_TOKENS = {"thorough", "fast"}
PROFILE_TOKENS = {"patch", "feature", "greenfield"}


def _looks_like_path(s: str) -> bool:
    return "/" in s or s.endswith(".md")


def _derive_artifact_type(path: Path) -> str | None:
    """Best-effort artifact_type from an artifact path.

    Routes by directory first (canonical layout per §5.5) and falls back to
    filename suffix. Returns None when neither signal applies, leaving the
    router to ask the operator."""
    parts = {p.lower() for p in path.parts}
    if "specs" in parts:
        return "spec"
    if "plans" in parts:
        return "plan"
    stem = path.stem.lower()
    if stem.endswith(("-design", "-spec", "-specification")):
        return "spec"
    if stem.endswith("-plan"):
        return "plan"
    return None


def _enumerate(state_root: Path) -> list[dict]:
    if not state_root.exists():
        return []
    out: list[dict] = []
    for d in state_root.iterdir():
        sp = d / "state.json"
        if not sp.is_file():
            continue
        state = json.loads(sp.read_text())
        # Track which artifact_type owns the latest block so the no-input and
        # slug-name match paths can emit it in their picker output. The router
        # needs artifact_type to call cr_state_init.py and cr_state_read.py.
        latest_block = None
        latest_artifact_type: str | None = None
        for art in ("spec", "plan"):
            block = state.get(art)
            if block is None:
                continue
            if latest_block is None or block["last_updated_at"] > latest_block["last_updated_at"]:
                latest_block = block
                latest_artifact_type = art
        active = (
            latest_block is not None and latest_block["current_stage"] != "ready_for_implementation"
        )
        pending = False
        if latest_block is not None:
            for art in ("spec", "plan"):
                block = state.get(art)
                if block is None:
                    continue
                for stage in block["completed_rounds"]:
                    if not (d / art / f"round-{stage}.json").exists():
                        pending = True
                        break
                if pending:
                    break
        out.append(
            {
                "slug": d.name,
                "artifact_type": latest_artifact_type,
                "active": active,
                "pending": pending,
                "last_updated_at": latest_block["last_updated_at"] if latest_block else "",
            }
        )
    return out


def _parse_input_tokens(raw: str) -> dict:
    """Split a multi-token --input string into a path/slug plus optional
    mode/profile tokens. Reserved words are recognised only as whole,
    standalone, whitespace-delimited tokens — never as filename substrings.

    Returns a dict with keys "target" (str), "mode" (str or None), and
    "review_profile" (str or None). Raises ValueError with an operator-facing
    diagnostic on a duplicate mode token, duplicate profile token, two
    path-like tokens, an unrecognised extra token, or a reserved token with
    no path/slug.
    """
    target: str | None = None
    mode: str | None = None
    profile: str | None = None
    tokens = raw.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Alias forms: --mode VALUE / --mode=VALUE, --review-profile VALUE / =VALUE
        matched_flag = False
        for flag, kind in (("--mode", "mode"), ("--review-profile", "profile")):
            value: str | None = None
            if tok == flag:
                if i + 1 >= len(tokens):
                    raise ValueError(f"{flag} requires a value")
                value = tokens[i + 1]
                i += 1
            elif tok.startswith(f"{flag}="):
                value = tok.split("=", 1)[1]
                if value == "":
                    raise ValueError(f"{flag}= requires a non-empty value")
            if value is not None:
                if kind == "mode":
                    if value not in MODE_TOKENS:
                        raise ValueError(f"invalid mode {value!r}")
                    if mode is not None:
                        raise ValueError("duplicate mode token")
                    mode = value
                else:
                    if value not in PROFILE_TOKENS:
                        raise ValueError(f"invalid review_profile {value!r}")
                    if profile is not None:
                        raise ValueError("duplicate profile token")
                    profile = value
                matched_flag = True
                break
        if not matched_flag:
            # Bare token: reserved word, or the lone path/slug.
            if tok in MODE_TOKENS:
                if mode is not None:
                    raise ValueError("duplicate mode token")
                mode = tok
            elif tok in PROFILE_TOKENS:
                if profile is not None:
                    raise ValueError("duplicate profile token")
                profile = tok
            elif _looks_like_path(tok) or _SLUG_RE.fullmatch(tok):
                if target is not None:
                    raise ValueError("two path/slug tokens supplied; expected one")
                target = tok
            else:
                raise ValueError(f"unrecognised token {tok!r}")
        i += 1
    if target is None:
        raise ValueError(
            "mode/profile tokens require an artifact path or slug"
            " (if your artifact is named after a reserved word like 'fast',"
            " pass it as a path, e.g. './fast')"
        )
    return {"target": target, "mode": mode, "review_profile": profile}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", help="Operator input (path or slug name).")
    args = p.parse_args()

    repo_root = find_repo_root(Path.cwd())
    state_root = state_dir(repo_root)
    slugs = _enumerate(state_root)

    if args.input:
        try:
            parsed = _parse_input_tokens(args.input)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        target = parsed["target"]
        extra = {}
        if parsed["mode"] is not None:
            extra["mode"] = parsed["mode"]
        if parsed["review_profile"] is not None:
            extra["review_profile"] = parsed["review_profile"]
        if _looks_like_path(target):
            path = Path(target)
            try:
                slug = derive_slug(path)
            except ValueError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1
            payload = {"slug": slug}
            artifact_type = _derive_artifact_type(path)
            if artifact_type is not None:
                payload["artifact_type"] = artifact_type
            payload.update(extra)
            print(canonical_json(payload))
            return 0
        match = next((s for s in slugs if s["slug"] == target), None)
        if match is not None:
            payload = {"slug": match["slug"]}
            if match["artifact_type"] is not None:
                payload["artifact_type"] = match["artifact_type"]
            payload.update(extra)
            print(canonical_json(payload))
            return 0
        # Treat as a new slug name. Validate against the same regex
        # `derive_slug` enforces — a bare slug-name input is just as
        # path-unsafe as a malicious filename if accepted unchecked.
        try:
            validate_slug(target)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        payload = {"slug": target}
        payload.update(extra)
        print(canonical_json(payload))
        return 0

    active = [s for s in slugs if s["active"]]
    if not active:
        print(canonical_json({"action": "ask_for_artifact_path"}))
        return 1
    if len(active) == 1:
        payload = {"slug": active[0]["slug"]}
        if active[0]["artifact_type"] is not None:
            payload["artifact_type"] = active[0]["artifact_type"]
        print(canonical_json(payload))
        return 0
    prioritized = sorted(active, key=lambda s: (not s["pending"], -ord_iso(s["last_updated_at"])))
    default = prioritized[0]["slug"]
    alternatives = [s["slug"] for s in prioritized[1:]]
    print(canonical_json({"default": default, "alternatives": alternatives}))
    return 0


def ord_iso(s: str) -> int:
    """Convert ISO 8601 to an ordering integer (for sort)."""
    digits = re.sub(r"[^0-9]", "", s)
    return int(digits or "0")


if __name__ == "__main__":
    sys.exit(main())
