#!/usr/bin/env python3
"""Pure routing decisions for impact-routed verification (issue #22).

decide_2a / decide_3a are pure functions over canonical on-disk state. Same
inputs produce byte-identical decisions across runs and hosts. The module
holds no I/O — callers (writer, reader CLI, status renderer) read state and
round files into dicts before invoking these functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RouteDecision:
    """The result of decide_2a / decide_3a.

    selected_slices is sorted and unique. fallback_reasons is sorted, unique,
    and empty iff scope == "narrow".
    """

    scope: Literal["broad", "narrow"]
    selected_slices: tuple[int, ...]
    fallback_reasons: tuple[str, ...]


def identify_mandatory_slices(slice_plan: list[dict]) -> dict:
    """Return {'global_coherence_slice': int|None, 'cross_artifact_slice': int|None}.

    `global_coherence_slice` is the agent_id of the highest-numbered slice
    with is_fixed=False, or None when no non-fixed slice exists (caller
    treats this as `mandatory_slice_undetectable`).

    `cross_artifact_slice` is the agent_id of the single is_fixed=True slice,
    or None when none is present.

    Raises ValueError when more than one is_fixed=True slice exists (the
    schema already enforces this; the writer treats >1 as defence-in-depth).
    """
    fixed = [s for s in slice_plan if s.get("is_fixed")]
    if len(fixed) > 1:
        raise ValueError(
            f"multiple is_fixed=True slices in slice_plan: {sorted(s['agent_id'] for s in fixed)}"
        )
    cross = fixed[0]["agent_id"] if fixed else None
    non_fixed = [s["agent_id"] for s in slice_plan if not s.get("is_fixed")]
    global_coh = max(non_fixed) if non_fixed else None
    return {"global_coherence_slice": global_coh, "cross_artifact_slice": cross}


def _broad(plan, reasons):
    """Build a broad RouteDecision over every slice in plan."""
    return RouteDecision(
        scope="broad",
        selected_slices=tuple(sorted(s["agent_id"] for s in plan)),
        fallback_reasons=tuple(sorted(set(reasons))),
    )


def decide_2a(block: dict, round_1a: dict, round_1b: dict) -> RouteDecision:
    """Decide the 2a scope for a single artifact block.

    `block` is state[artifact_type] (the per-artifact block, not the full
    state). `round_1a` is the canonical round-1a envelope (used for
    slice_plan). `round_1b` is the canonical round-1b envelope (used for
    adjudications + changelog + accepted_findings).
    """
    slice_plan = round_1a["slice_plan"]
    # Multiple is_fixed=True slices means state is structurally invalid; per
    # spec §4.3 we refuse the decision (the schema already enforces a single
    # cross-artifact slice; this propagation is defence-in-depth that the
    # writer treats as a hard refusal). Let the ValueError propagate to the
    # caller.
    mandatory = identify_mandatory_slices(slice_plan)

    reasons: list[str] = []
    mode = block.get("mode")
    profile = block.get("review_profile")
    if profile is None:
        reasons.append("F2-4")
    elif profile == "greenfield":
        reasons.append("F2-5")
    if mode != "fast":
        reasons.append("F2-6")
    if mandatory["global_coherence_slice"] is None:
        reasons.append("F2-7")

    # Author-field completeness — apply even if the profile already disqualified
    # the route, so `--verbose` can surface every reason.
    accepted_ids = {f["id"] for f in round_1b.get("accepted_findings", [])}
    for adj in round_1b.get("adjudications", []):
        if adj.get("verdict") != "accept":
            continue
        if not adj.get("fix_criterion") or not adj.get("verification_target"):
            reasons.append("F2-1")
            break
    for entry in round_1b.get("changelog", []):
        if entry["finding_id"] not in accepted_ids:
            continue
        if "additional_affected_slices" not in entry:
            reasons.append("F2-2")
            break
    valid_agent_ids = {s["agent_id"] for s in slice_plan}
    for entry in round_1b.get("changelog", []):
        if entry["finding_id"] not in accepted_ids:
            continue
        for aid in entry.get("additional_affected_slices", []):
            if aid not in valid_agent_ids:
                reasons.append("F2-3")
                break
        if "F2-3" in reasons:
            break

    if reasons:
        return _broad(slice_plan, reasons)

    selected: set[int] = set()
    # Origin slices from accepted findings (id format R1-<agent_id>-NNN).
    for fid in accepted_ids:
        selected.add(int(fid.split("-")[1]))
    # Author-declared cross-slice impacts.
    for entry in round_1b.get("changelog", []):
        if entry["finding_id"] not in accepted_ids:
            continue
        selected.update(entry.get("additional_affected_slices", []))
    # F2-7 above ensures global_coherence_slice is not None on the narrow path.
    global_coh = mandatory["global_coherence_slice"]
    assert global_coh is not None  # noqa: S101 - narrows type; invariant from F2-7
    selected.add(global_coh)
    if mandatory["cross_artifact_slice"] is not None:
        selected.add(mandatory["cross_artifact_slice"])

    return RouteDecision(
        scope="narrow",
        selected_slices=tuple(sorted(selected)),
        fallback_reasons=(),
    )
