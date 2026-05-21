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


def decide_3a(
    block: dict,
    round_1a: dict,
    round_1b: dict,
    round_2a: dict,
    round_2b: dict,
) -> RouteDecision:
    """Decide the 3a scope. Allowed only for `patch + fast` with no fallback;
    otherwise broad."""
    slice_plan = round_1a["slice_plan"]
    # Same refusal contract as decide_2a (spec §4.3): a multiple-is_fixed
    # slice_plan is invalid state, not a broad-fallback condition. Let
    # ValueError propagate.
    mandatory = identify_mandatory_slices(slice_plan)

    reasons: list[str] = []

    # F3-2: patch + fast gate.
    if block.get("mode") != "fast" or block.get("review_profile") != "patch":
        reasons.append("F3-2")
    # F3-1 (mandatory-slice-undetectable variant): collapsed with F2-7 since
    # this gate is structurally identical to decide_2a's, and surfaces under
    # the F3-1 umbrella here.
    if mandatory["global_coherence_slice"] is None:
        reasons.append("F3-1")

    # F3-1: F2-1..F2-3 / F2-7 applied to the 2b envelope.
    accepted_2b_ids = {f["id"] for f in round_2b.get("accepted_findings", [])}
    valid_agent_ids = {s["agent_id"] for s in slice_plan}
    for adj in round_2b.get("adjudications", []):
        if adj.get("verdict") != "accept":
            continue
        if not adj.get("fix_criterion") or not adj.get("verification_target"):
            reasons.append("F3-1")
            break
    for entry in round_2b.get("changelog", []):
        if entry["finding_id"] not in accepted_2b_ids:
            continue
        if "additional_affected_slices" not in entry:
            reasons.append("F3-1")
            break
        bad = False
        for aid in entry.get("additional_affected_slices", []):
            if aid not in valid_agent_ids:
                reasons.append("F3-1")
                bad = True
                break
        if bad:
            break

    # F3-3: any 2a verification not fully resolved.
    for agent in round_2a.get("agents", []):
        triggered = False
        for v in agent.get("round_1_verifications", []):
            if v.get("status") in {"not_resolved", "partially_resolved"}:
                reasons.append("F3-3")
                triggered = True
                break
        if triggered:
            break

    # F3-4: any accepted 2a blocker.
    for f in round_2b.get("accepted_findings", []):
        if f.get("severity") == "blocker":
            reasons.append("F3-4")
            break

    # F3-5: every accepted 1b finding must have a 1b lineage row, every accepted
    # 2b finding must have a fresh 2b lineage row, every 1b lineage row must
    # carry forward into 2b with latest_verification populated, and every 2b
    # carry-forward row must preserve the affected_slices its 1b row declared.
    # The accepted-without-lineage checks fail closed when the writer skipped
    # lineage emission (LINEAGE_INCOMPLETE stderr) for an accepted finding —
    # otherwise an empty/partial lineage set would make the carry-forward check
    # vacuously pass and narrow 3a could skip a slice Round 1 or Round 2
    # actually edited. The carry-forward affected_slices check defends against
    # paste-imported or hand-edited 2b state where a row points to a 1b row by
    # prior_lineage_id but silently shrinks its affected_slices set.
    accepted_1b_ids = {f["id"] for f in round_1b.get("accepted_findings", [])}
    lineage_1b_by_origin = {
        row["original_finding_id"]: row for row in round_1b.get("finding_lineage", [])
    }
    if accepted_1b_ids - lineage_1b_by_origin.keys():
        reasons.append("F3-5")
    lineage_1b_by_id = {row["lineage_id"]: row for row in round_1b.get("finding_lineage", [])}
    lineage_2b = round_2b.get("finding_lineage", [])
    carried_priors = {row.get("prior_lineage_id") for row in lineage_2b}
    if lineage_1b_by_id.keys() - carried_priors:
        reasons.append("F3-5")
    accepted_2b_ids = {f["id"] for f in round_2b.get("accepted_findings", [])}
    lineage_2b_fresh_origins = {
        row["original_finding_id"] for row in lineage_2b if row.get("originating_stage") == "2a"
    }
    if accepted_2b_ids - lineage_2b_fresh_origins:
        reasons.append("F3-5")
    for row in lineage_2b:
        if row.get("originating_stage") == "1a" and row.get("latest_verification") is None:
            reasons.append("F3-5")
            break
        prior_id = row.get("prior_lineage_id")
        if prior_id is None:
            continue
        prior = lineage_1b_by_id.get(prior_id)
        if prior is None:
            continue  # already caught by the carry-forward set-difference above
        prior_affected = set(prior.get("affected_slices", []))
        current_affected = set(row.get("affected_slices", []))
        if prior_affected - current_affected:
            reasons.append("F3-5")
            break

    if reasons:
        return _broad(slice_plan, reasons)

    selected: set[int] = set()
    for row in lineage_2b:
        selected.update(row.get("affected_slices", []))
    global_coh = mandatory["global_coherence_slice"]
    assert global_coh is not None  # noqa: S101 - narrows type; invariant from F3-1 mandatory-slice check
    selected.add(global_coh)
    if mandatory["cross_artifact_slice"] is not None:
        selected.add(mandatory["cross_artifact_slice"])
    return RouteDecision(
        scope="narrow",
        selected_slices=tuple(sorted(selected)),
        fallback_reasons=(),
    )
