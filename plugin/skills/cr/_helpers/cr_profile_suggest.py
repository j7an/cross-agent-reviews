#!/usr/bin/env python3
"""Deterministic, explainable profile/mode suggestion for /cr init (issue #35).

Pure functions derive a suggestion from artifact TEXT only — no filesystem,
no git, no Path.exists. The suggestion is advisory data recorded in state and
printed by the read-only `/cr suggest` preview; it NEVER participates in
routing. See docs/superpowers/specs/2026-05-21-issue-35-profile-suggestion-design.md.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

RULESET_VERSION = 1

# Safety order: index = review breadth. Conflict/insufficient escalate right.
SAFETY_ORDER = ("patch", "feature", "greenfield")

# --- Extraction thresholds (named constants; surfaced in `signals`) ---
DENSITY_HIGH_ABS = 5  # line-anchored refs at/above this -> high
DENSITY_HIGH_RATIO = 0.5  # ... or this anchored/total ratio with >=3 refs
FANOUT_DIRS = 4  # distinct directories -> broad fan-out
SMALL_FILES = 3  # at/below this referenced-path count is "small"
CHECKLIST_MIN = 3  # checklist items needed to call a plan checklist-y
PATHS_LIST_CAP = 200  # bound the persisted path list

# A path-like token: >=1 slash and a dotted filename, optional :line anchor.
_PATH_RE = re.compile(r"\b([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.[A-Za-z0-9]+)(?::(\d+))?")
_CREATION_RE = re.compile(
    r"\b(create (?:a )?new|new module|new package|new director(?:y|ies)|"
    r"new subsystem|from scratch|greenfield|scaffold)\b",
    re.IGNORECASE,
)
_CHECKLIST_RE = re.compile(r"^\s*[-*] \[[ xX]\]")
_ARCH_HEADING_RE = re.compile(
    r"^#{1,4}\s+(architecture|components?|data flow|system design|overview)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _categorize(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "/tests/" in path
        or path.startswith("tests/")
    ):
        return "tests"
    if path.startswith("docs/") or "/docs/" in path or name.endswith(".md"):
        return "docs"
    if "/_shared/" in path:
        return "shared_templates"
    if "schema" in path and name.endswith(".json"):
        return "schemas"
    if name.startswith("round-"):
        return "round_docs"
    if "/_helpers/" in path:
        return "helpers"
    return "other"


def _density_bucket(anchored: int, total: int) -> str:
    if total == 0 or anchored == 0:
        return "low"
    ratio = anchored / total
    if anchored >= DENSITY_HIGH_ABS or (total >= 3 and ratio >= DENSITY_HIGH_RATIO):
        return "high"
    return "med"


def extract_signals(artifact_text: str, artifact_type: str) -> dict:
    """Derive the bounded, deterministic signal vector from artifact text."""
    paths: list[str] = []
    anchored = 0
    seen: set[str] = set()
    for m in _PATH_RE.finditer(artifact_text):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            paths.append(path)
        if m.group(2) is not None:
            anchored += 1
    paths_sorted = sorted(seen)
    dirs = sorted({p.rsplit("/", 1)[0] for p in paths_sorted if "/" in p})

    categories: dict[str, int] = {}
    for p in paths_sorted:
        cat = _categorize(p)
        categories[cat] = categories.get(cat, 0) + 1

    total = len(paths_sorted)
    docs_only = total > 0 and categories.get("docs", 0) == total
    tests_only = total > 0 and categories.get("tests", 0) == total

    creation = len(_CREATION_RE.findall(artifact_text))

    cross_artifact = sum(1 for p in paths_sorted if re.search(r"docs/(specs|plans)/", p))

    checklist_items = sum(1 for line in artifact_text.splitlines() if _CHECKLIST_RE.match(line))
    prose_lines = sum(
        1
        for line in artifact_text.splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
        and not _CHECKLIST_RE.match(line)
        and not line.lstrip().startswith("```")
    )
    checklist_only = checklist_items >= CHECKLIST_MIN and prose_lines <= checklist_items

    signals = {
        "artifact_type": artifact_type,
        "referenced_file_paths_count": total,
        "referenced_file_paths": paths_sorted[:PATHS_LIST_CAP],
        "referenced_directories_count": len(dirs),
        "referenced_directories": dirs[:PATHS_LIST_CAP],
        "line_anchored_refs": anchored,
        "existing_ref_density": _density_bucket(anchored, total),
        "creation_markers": creation,
        "file_category_counts": categories,
        "docs_only": docs_only,
        "tests_only": tests_only,
        "cross_artifact_dependency_count": cross_artifact,
        "checklist_item_count": checklist_items,
        "checklist_only": checklist_only,
        "architecture_section_present": bool(_ARCH_HEADING_RE.search(artifact_text)),
    }
    return signals


# --- Rule tables. Each entry: (rule_id, votes_profile, predicate). ---
# Resolution is value-based (broadest fired profile); ordering is display-only.


def _plan_rules() -> list[tuple[str, str, Callable[[dict], bool]]]:
    return [
        ("R-NEW-SUBSYSTEM", "greenfield", lambda s: s["creation_markers"] >= 1),
        (
            "R-BROAD-FANOUT",
            "feature",
            lambda s: (
                s["referenced_directories_count"] >= FANOUT_DIRS and s["creation_markers"] == 0
            ),
        ),
        ("R-CROSS-ARTIFACT-DEPS", "feature", lambda s: s["cross_artifact_dependency_count"] >= 2),
        ("R-DOCS-ONLY", "patch", lambda s: s["docs_only"]),
        ("R-TESTS-ONLY", "patch", lambda s: s["tests_only"]),
        (
            "R-HIGH-EXISTING-REF-DENSITY",
            "patch",
            lambda s: s["existing_ref_density"] == "high" and s["creation_markers"] == 0,
        ),
        (
            "R-CHECKLIST-SMALL",
            "patch",
            lambda s: (
                s["checklist_only"]
                and s["referenced_file_paths_count"] <= SMALL_FILES
                and s["creation_markers"] == 0
            ),
        ),
    ]


def _spec_rules() -> list[tuple[str, str, Callable[[dict], bool]]]:
    return [
        ("R-NEW-SUBSYSTEM", "greenfield", lambda s: s["creation_markers"] >= 1),
        (
            "R-ARCH-PROPOSAL",
            "greenfield",
            lambda s: s["architecture_section_present"] and s["existing_ref_density"] == "low",
        ),
        (
            "R-FEATURE-SPEC",
            "feature",
            lambda s: (
                s["architecture_section_present"] and s["existing_ref_density"] in ("med", "high")
            ),
        ),
        ("R-DOCS-ONLY", "patch", lambda s: s["docs_only"]),
        (
            "R-TARGETED-SPEC",
            "patch",
            lambda s: (
                s["existing_ref_density"] == "high"
                and not s["architecture_section_present"]
                and s["creation_markers"] == 0
            ),
        ),
    ]


def _rules_for(artifact_type: str) -> list[tuple[str, str, Callable[[dict], bool]]]:
    if artifact_type == "spec":
        return _spec_rules()
    if artifact_type == "plan":
        return _plan_rules()
    raise ValueError(f"unknown artifact_type {artifact_type!r}")


def _broadest(profiles: set[str]) -> str:
    return max(profiles, key=SAFETY_ORDER.index)


def _matched_signals(rule_id: str, signals: dict) -> dict:
    """Bounded, rule-relevant signal values for the evidence trail."""
    keys_by_rule = {
        "R-NEW-SUBSYSTEM": ["creation_markers"],
        "R-BROAD-FANOUT": ["referenced_directories_count", "creation_markers"],
        "R-CROSS-ARTIFACT-DEPS": ["cross_artifact_dependency_count"],
        "R-DOCS-ONLY": ["docs_only", "referenced_file_paths_count"],
        "R-TESTS-ONLY": ["tests_only", "referenced_file_paths_count"],
        "R-HIGH-EXISTING-REF-DENSITY": ["existing_ref_density", "line_anchored_refs"],
        "R-CHECKLIST-SMALL": ["checklist_only", "referenced_file_paths_count"],
        "R-ARCH-PROPOSAL": ["architecture_section_present", "existing_ref_density"],
        "R-FEATURE-SPEC": ["architecture_section_present", "existing_ref_density"],
        "R-TARGETED-SPEC": ["existing_ref_density", "architecture_section_present"],
    }
    return {k: signals[k] for k in keys_by_rule.get(rule_id, [])}


def suggest(signals: dict, artifact_type: str) -> dict:
    """Apply rule tables and resolve. Returns the rule-resolution evidence
    portion (no hash / ruleset_version — see suggest_for_artifact_bytes)."""
    fired = [
        {
            "rule_id": rid,
            "kind": "profile",
            "votes_profile": prof,
            "matched_signals": _matched_signals(rid, signals),
        }
        for (rid, prof, pred) in _rules_for(artifact_type)
        if pred(signals)
    ]

    if not fired:
        resolution = "insufficient_evidence"
        selected = "greenfield"
        reason = {"rule_id": "R-INSUFFICIENT-EVIDENCE", "selected_profile": selected}
    else:
        profiles = {r["votes_profile"] for r in fired}
        selected = _broadest(profiles)
        ids = sorted(r["rule_id"] for r in fired)
        if len(fired) == 1:
            resolution = "single"
            reason = {"rule_id": "R-SINGLE-RULE", "selected_profile": selected}
        elif len(profiles) == 1:
            resolution = "agreement"
            reason = {
                "rule_id": "R-RULE-AGREEMENT",
                "competing_rules": ids,
                "selected_profile": selected,
            }
        else:
            resolution = "conflict"
            reason = {
                "rule_id": "R-CONFLICT-ESCALATION",
                "competing_rules": ids,
                "selected_profile": selected,
            }

    fast_eligible = selected == "patch"
    if fast_eligible:
        fired.append(
            {
                "rule_id": "R-FAST-ELIGIBLE-PATCH",
                "kind": "mode",
                "matched_signals": {"resolved_profile": selected},
            }
        )
    suggested_mode = "fast" if fast_eligible else "thorough"

    return {
        "resolution": resolution,
        "suggested_review_profile": selected,
        "suggested_mode": suggested_mode,
        "fast_eligible": fast_eligible,
        "fired_rules": fired,
        "resolution_reason": reason,
        "signals": signals,
    }


def suggest_for_artifact_bytes(artifact_bytes: bytes, artifact_type: str) -> dict:
    """Hash-bound public entry point. Stamps ruleset_version, artifact_type,
    and artifact_content_hash so the evidence binds to the exact bytes."""
    from _cr_lib import compute_content_hash_bytes

    text = artifact_bytes.decode("utf-8", errors="replace")
    core = suggest(extract_signals(text, artifact_type), artifact_type)
    return {
        "ruleset_version": RULESET_VERSION,
        "artifact_type": artifact_type,
        "artifact_content_hash": compute_content_hash_bytes(artifact_bytes),
        **core,
    }


def _human_summary(ev: dict) -> str:
    reason = ev["resolution_reason"]
    competing = reason.get("competing_rules")
    tail = f" (competing: {', '.join(competing)})" if competing else ""
    return (
        f"suggested: profile={ev['suggested_review_profile']} "
        f"mode={ev['suggested_mode']} (fast_eligible="
        f"{'yes' if ev['fast_eligible'] else 'no'})  "
        f"[{reason['rule_id']}{tail}]"
    )


def main() -> int:
    import argparse
    import sys
    from pathlib import Path

    from _cr_lib import canonical_json, err
    from cr_state_pick_slug import _derive_artifact_type

    p = argparse.ArgumentParser(description="Read-only profile/mode suggestion preview.")
    p.add_argument("--artifact-path", required=True, type=Path)
    p.add_argument("--artifact-type", choices=["spec", "plan"])
    args = p.parse_args()

    artifact = args.artifact_path
    if not artifact.is_absolute():
        artifact = (Path.cwd() / artifact).resolve()
    if not artifact.is_file():
        return err(f"artifact path not found: {artifact}", code=2)

    artifact_type = args.artifact_type or _derive_artifact_type(artifact)
    if artifact_type is None:
        return err(
            "could not derive --artifact-type from path; pass --artifact-type spec|plan "
            "(preview is non-interactive and will not guess)."
        )

    ev = suggest_for_artifact_bytes(artifact.read_bytes(), artifact_type)
    sys.stdout.write(canonical_json(ev) + "\n")
    sys.stderr.write(_human_summary(ev) + "\n")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
