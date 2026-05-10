#!/usr/bin/env python3
"""Extract spec placeholders + plan-only concrete values for the cross-artifact slice.

Mechanical step: pattern detection, location pinpointing, deterministic
correspondence ranking. Does NOT classify (preserved / cited / hallucinated /
flagged) — that is the LLM sub-agent's job. Output goes to stdout as JSON.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _cr_lib import canonical_json

SENTINEL = "☃"  # ☃ snowman; cannot occur in normal markdown text

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("unverified-marker", re.compile(r"<unverified[^>]*>")),
    ("user-token", re.compile(r"<your-[a-z0-9-]+>")),
    ("angle-bracket", re.compile(r"<[A-Za-z0-9_-]+>")),
    ("template-var", re.compile(r"\$\{[A-Za-z0-9_]+\}")),
    ("double-underscore", re.compile(r"__[A-Z0-9_]+__")),
    ("todo-marker", re.compile(r"\b(?:TODO|TBD|FIXME)\b")),
)

CONCRETE_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("file-path", re.compile(r"`[A-Za-z0-9_./-]+\.(?:py|sh|md|json|yaml|yml|toml)`")),
    ("version-pin", re.compile(r"`v\d+\.\d+\.\d+(?:[-+][\w.]+)?`")),
    ("hash", re.compile(r"`[A-Fa-f0-9]{7,64}`")),
    ("port", re.compile(r"`[0-9]{1,5}`")),
    ("id", re.compile(r"`\d{6,}`")),
)


def _alphanumeric_tokens(line: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z0-9]+", line) if len(t) >= 3}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _scan_spec(text: str) -> list[dict]:
    out: list[dict] = []
    seen_at: set[tuple[int, int]] = set()
    for line_idx, line in enumerate(text.splitlines(), start=1):
        for kind, pat in PATTERNS:
            for m in pat.finditer(line):
                key = (line_idx, m.start())
                if key in seen_at:
                    continue
                seen_at.add(key)
                literal = m.group(0)
                anchor = line.replace(literal, SENTINEL).strip()
                out.append(
                    {
                        "pattern_kind": kind,
                        "literal": literal,
                        "spec_location": f"line {line_idx}",
                        "_anchor": anchor,
                        "_anchor_tokens": _alphanumeric_tokens(anchor.replace(SENTINEL, "")),
                    }
                )
    return out


def _has_citation(line: str) -> bool:
    # Use a word-boundary regex for `verified` so the substring inside
    # `unverified` does NOT count as a citation — the unverified marker is
    # the explicit "needs lookup" signal, the opposite of a citation, and
    # the prior `"verified" in line.lower()` test silently flipped its
    # classification. `\b` does not break on letter-letter adjacency, so
    # `\bverified\b` matches `... verified via ...` but not `... unverified
    # ...`. The `_is_unverified_flag` check below is a belt-and-braces guard
    # in case the input has unusual punctuation around the marker.
    lower = line.lower()
    if _is_unverified_flag(line):
        return False
    has_verified_word = bool(re.search(r"\bverified\b", lower))
    return (
        has_verified_word
        or bool(re.search(r"\(see [^)]+\)", line))
        or bool(re.search(r"`[a-z]+\b[^`]+`", line) and "via" in lower)
    )


def _is_unverified_flag(line: str) -> bool:
    return "<unverified" in line.lower()


JACCARD_THRESHOLD = 0.6
# Minimum number of non-sentinel, non-whitespace anchor characters required
# before the sentinel-regex fallback is allowed to fire. With no minimum, a
# spec line whose anchor is just the placeholder (e.g. `<X>` on a line by
# itself) collapses to `re.escape(SENTINEL).replace(SENTINEL, r"\S+") ==
# r"\S+"`, which matches any nonblank token in any plan line and would
# falsely flag the placeholder as substituted against the first nonblank
# plan line encountered. Three characters is the smallest guard that still
# allows compact anchors like `is <X>` while excluding `<X>`-only lines and
# anchors with only stray punctuation around the sentinel; lines below the
# threshold fall back to Jaccard scoring alone (which already handles the
# token-overlap case correctly).
MIN_ANCHOR_NON_SENTINEL_CHARS = 3


def _correspondence(placeholder: dict, plan_lines: list[str]) -> dict:
    anchor = placeholder["_anchor"]
    anchor_tokens = placeholder["_anchor_tokens"]
    # Pre-compute once: sentinel fallback is only safe when the anchor has
    # enough non-sentinel context to disambiguate matches. See
    # MIN_ANCHOR_NON_SENTINEL_CHARS for rationale.
    sentinel_fallback_allowed = (
        SENTINEL in anchor
        and len(re.sub(r"\s+", "", anchor.replace(SENTINEL, ""))) >= MIN_ANCHOR_NON_SENTINEL_CHARS
    )
    candidates: list[tuple[int, str, float]] = []
    for line_idx, line in enumerate(plan_lines, start=1):
        plan_tokens = _alphanumeric_tokens(line)
        score = _jaccard(anchor_tokens, plan_tokens)
        sentinel_match = False
        if sentinel_fallback_allowed:
            wildcard = re.escape(anchor).replace(re.escape(SENTINEL), r"\S+")
            if re.search(wildcard, line):
                sentinel_match = True
        # 0.6 is the spec-locked threshold (§7.3 step 3, §7.3 step 5
        # rationale). It is the lowest empirical value that reliably matches
        # reformatted-but-equivalent lines (reordered clauses, minor wording
        # changes) without conflating distinct lines that share boilerplate.
        # The threshold is locked for v0.1.x; fixtures must be authored so
        # the plan line shares ≥0.6 of its anchor-tokens with the spec line
        # (after stripping the placeholder literal). The sentinel-regex
        # fallback handles the edge case where surrounding prose diverges
        # but the anchor structure is preserved verbatim around the
        # substitution point — gated by `sentinel_fallback_allowed` so a
        # placeholder-only line cannot turn it into a `\S+` wildcard.
        if score >= JACCARD_THRESHOLD or sentinel_match:
            candidates.append((line_idx, line, max(score, 1.0 if sentinel_match else 0.0)))
    if not candidates:
        return {
            "found": False,
            "multiple_candidates": False,
            "candidates": [],
            "unmatched_reason": "no_plan_line_above_threshold",
        }
    candidates.sort(key=lambda c: (-c[2], c[0]))
    primary = candidates[0]
    base = {
        "found": True,
        "multiple_candidates": len(candidates) > 1,
        "literal": primary[1].strip(),
        "plan_location": f"line {primary[0]}",
        # Substituted iff the original spec placeholder literal does NOT
        # appear in the matched plan line. The earlier SENTINEL clause was
        # always True (real plan text never contains the snowman) and made
        # `is_substituted` fire even for verbatim preservation, breaking the
        # cross-artifact rubric's hallucination classification.
        "is_substituted": placeholder["literal"] not in primary[1],
        "is_flagged_unverified": _is_unverified_flag(primary[1]),
        "has_inline_citation": _has_citation(primary[1]),
        "candidates": [],
        "unmatched_reason": None,
    }
    if base["multiple_candidates"]:
        base["candidates"] = [
            {"literal": c[1].strip(), "plan_location": f"line {c[0]}", "jaccard": round(c[2], 3)}
            for c in candidates
        ]
    return base


def _scan_plan_only_concrete(plan_text: str, spec_text: str) -> list[dict]:
    out: list[dict] = []
    for line_idx, line in enumerate(plan_text.splitlines(), start=1):
        for kind, pat in CONCRETE_KINDS:
            for m in pat.finditer(line):
                literal = m.group(0).strip("`")
                if literal in spec_text:
                    continue
                out.append(
                    {
                        "literal": literal,
                        "kind": kind,
                        "plan_location": f"line {line_idx}",
                        "is_flagged_unverified": _is_unverified_flag(line),
                        "has_inline_citation": _has_citation(line),
                    }
                )
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--spec-path", required=True, type=Path)
    p.add_argument("--plan-path", required=True, type=Path)
    args = p.parse_args()
    if not args.spec_path.is_file() or not args.plan_path.is_file():
        print("ERROR: spec or plan path not found.", file=sys.stderr)
        return 2
    spec_text = args.spec_path.read_text()
    plan_text = args.plan_path.read_text()
    plan_lines = plan_text.splitlines()
    placeholders = _scan_spec(spec_text)
    out = {
        "spec_path": str(args.spec_path),
        "plan_path": str(args.plan_path),
        "spec_placeholders": [],
        "plan_only_concrete_values": _scan_plan_only_concrete(plan_text, spec_text),
    }
    for ph in placeholders:
        report = {
            "pattern_kind": ph["pattern_kind"],
            "literal": ph["literal"],
            "spec_location": ph["spec_location"],
            "plan_correspondence": _correspondence(ph, plan_lines),
        }
        out["spec_placeholders"].append(report)
    sys.stdout.write(canonical_json(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
