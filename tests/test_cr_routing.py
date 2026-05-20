"""Tests for cr_routing.identify_mandatory_slices + RouteDecision dataclass."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from cr_routing import RouteDecision, decide_2a, identify_mandatory_slices


def _slice_plan_spec():
    """Five-slice plan for a spec review (no cross-artifact slice)."""
    return [
        {"agent_id": 1, "concern": "Data model", "slice_definition": "...", "is_fixed": False},
        {"agent_id": 2, "concern": "Error handling", "slice_definition": "...", "is_fixed": False},
        {
            "agent_id": 3,
            "concern": "Acceptance criteria",
            "slice_definition": "...",
            "is_fixed": False,
        },
        {"agent_id": 4, "concern": "Consistency", "slice_definition": "...", "is_fixed": False},
        {
            "agent_id": 5,
            "concern": "Global coherence",
            "slice_definition": "...",
            "is_fixed": False,
        },
    ]


def _slice_plan_plan_with_cross_artifact():
    """Six-slice plan: agents 1-5 + agent 6 cross-artifact (is_fixed=True)."""
    return [
        *_slice_plan_spec(),
        {
            "agent_id": 6,
            "concern": "Cross-artifact integrity",
            "slice_definition": "...",
            "is_fixed": True,
        },
    ]


def test_route_decision_is_frozen():
    d = RouteDecision(scope="narrow", selected_slices=(1, 2), fallback_reasons=())
    with pytest.raises(FrozenInstanceError):
        d.scope = "broad"  # type: ignore[misc]


def test_identify_mandatory_slices_spec_only():
    result = identify_mandatory_slices(_slice_plan_spec())
    assert result == {"global_coherence_slice": 5, "cross_artifact_slice": None}


def test_identify_mandatory_slices_plan_with_cross_artifact():
    result = identify_mandatory_slices(_slice_plan_plan_with_cross_artifact())
    assert result == {"global_coherence_slice": 5, "cross_artifact_slice": 6}


def test_identify_mandatory_slices_global_coherence_is_highest_non_fixed():
    # Even with cross-artifact slice 6, the global-coherence slice is the
    # highest agent_id among is_fixed=False slices (which is 5 here).
    plan = [
        {"agent_id": 1, "concern": "a", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 6, "concern": "cross", "slice_definition": "x", "is_fixed": True},
    ]
    # Only one non-fixed slice -> that one is the global-coherence slice.
    assert identify_mandatory_slices(plan) == {
        "global_coherence_slice": 1,
        "cross_artifact_slice": 6,
    }


def test_identify_mandatory_slices_no_non_fixed_slices_is_undetectable():
    plan = [{"agent_id": 6, "concern": "cross", "slice_definition": "x", "is_fixed": True}]
    result = identify_mandatory_slices(plan)
    assert result["global_coherence_slice"] is None
    assert result["cross_artifact_slice"] == 6


def test_identify_mandatory_slices_multiple_fixed_raises():
    plan = [
        {"agent_id": 1, "concern": "a", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 5, "concern": "cross1", "slice_definition": "x", "is_fixed": True},
        {"agent_id": 6, "concern": "cross2", "slice_definition": "x", "is_fixed": True},
    ]
    with pytest.raises(ValueError, match="multiple is_fixed"):
        identify_mandatory_slices(plan)


def _state(*, mode=None, review_profile=None):
    block = {
        "path": "spec.md",
        "current_stage": "round_2a_pending",
        "completed_rounds": ["1a", "1b"],
    }
    if mode is not None:
        block["mode"] = mode
    if review_profile is not None:
        block["review_profile"] = review_profile
    return {"slug": "demo", "schema_version": 1, "spec": block}


def _round_1a(slice_plan):
    return {"stage": "1a", "slice_plan": slice_plan, "agents": []}


def _round_1b(*, accepted=(), changelog=(), adjudications=()):
    """Build a minimal-but-shape-correct 1b envelope.

    `accepted` is a list of (finding_id, adjudication_extras_dict) pairs.
    `changelog` is a list of dict (finding_id + change_made + optional fields).
    `adjudications` defaults to one adjudication per accepted finding with the
    extras merged in; pass an explicit list when a test needs reject verdicts
    or absent fix_criterion/verification_target."""
    if not adjudications:
        adjudications = [
            {"finding_id": fid, "verdict": "accept", "reasoning": "ok", **extras}
            for fid, extras in accepted
        ]
    return {
        "stage": "1b",
        "slice_plan": [],  # the route function reads slice_plan from the 1a envelope
        "adjudications": list(adjudications),
        "accepted_findings": [{"id": fid} for fid, _ in accepted],
        "rejected_findings": [],
        "changelog": list(changelog),
        "self_review": [],
    }


def test_decide_2a_patch_fast_complete_lineage_narrow():
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1a = _round_1a(plan)
    r1b = _round_1b(
        accepted=[
            ("R1-1-001", {"fix_criterion": "c", "verification_target": "t"}),
        ],
        changelog=[
            {"finding_id": "R1-1-001", "change_made": "edit", "additional_affected_slices": [3]},
        ],
    )
    decision = decide_2a(state, r1a, r1b)
    assert decision.scope == "narrow"
    assert decision.selected_slices == (1, 3, 5)  # origin 1 + impact 3 + global-coh 5
    assert decision.fallback_reasons == ()


def test_decide_2a_legacy_state_falls_back_F2_4():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state()["spec"]  # no mode, no review_profile
    decision = decide_2a(state, _round_1a(plan), _round_1b())
    assert decision.scope == "broad"
    assert "F2-4" in decision.fallback_reasons
    assert set(decision.selected_slices) == {1, 2, 3, 4, 5}


def test_decide_2a_greenfield_falls_back_F2_5():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="greenfield")["spec"]
    decision = decide_2a(state, _round_1a(plan), _round_1b())
    assert decision.scope == "broad"
    assert "F2-5" in decision.fallback_reasons


def test_decide_2a_thorough_mode_falls_back_F2_6():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="thorough", review_profile="patch")["spec"]
    decision = decide_2a(state, _round_1a(plan), _round_1b())
    assert decision.scope == "broad"
    assert "F2-6" in decision.fallback_reasons


def test_decide_2a_missing_fix_criterion_falls_back_F2_1():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1b = _round_1b(
        accepted=[("R1-1-001", {"verification_target": "t"})],  # missing fix_criterion
        changelog=[
            {"finding_id": "R1-1-001", "change_made": "edit", "additional_affected_slices": []}
        ],
    )
    decision = decide_2a(state, _round_1a(plan), r1b)
    assert decision.scope == "broad"
    assert "F2-1" in decision.fallback_reasons


def test_decide_2a_missing_additional_affected_slices_falls_back_F2_2():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1b = _round_1b(
        accepted=[("R1-1-001", {"fix_criterion": "c", "verification_target": "t"})],
        changelog=[{"finding_id": "R1-1-001", "change_made": "edit"}],  # no field
    )
    decision = decide_2a(state, _round_1a(plan), r1b)
    assert decision.scope == "broad"
    assert "F2-2" in decision.fallback_reasons


def test_decide_2a_empty_affected_slices_is_explicit_negative_not_F2_2():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1b = _round_1b(
        accepted=[("R1-1-001", {"fix_criterion": "c", "verification_target": "t"})],
        changelog=[
            {"finding_id": "R1-1-001", "change_made": "edit", "additional_affected_slices": []},
        ],
    )
    decision = decide_2a(state, _round_1a(plan), r1b)
    assert decision.scope == "narrow"
    assert decision.selected_slices == (1, 5)  # origin + global-coh, no cross-slice impact
    assert decision.fallback_reasons == ()


def test_decide_2a_unknown_agent_id_in_affected_slices_falls_back_F2_3():  # noqa: N802
    plan = _slice_plan_spec()  # agent_ids 1..5
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1b = _round_1b(
        accepted=[("R1-1-001", {"fix_criterion": "c", "verification_target": "t"})],
        changelog=[
            {"finding_id": "R1-1-001", "change_made": "edit", "additional_affected_slices": [6]},
        ],
    )
    decision = decide_2a(state, _round_1a(plan), r1b)
    assert decision.scope == "broad"
    assert "F2-3" in decision.fallback_reasons


def test_decide_2a_mandatory_slice_undetectable_falls_back_F2_7():  # noqa: N802
    # Single is_fixed=True slice with no non-fixed slices -> no global-coherence
    # slice computable. (Multiple is_fixed=True slices raises instead; see
    # the next test.)
    plan = [{"agent_id": 6, "concern": "cross", "slice_definition": "x", "is_fixed": True}]
    state = _state(mode="fast", review_profile="patch")["spec"]
    decision = decide_2a(state, _round_1a(plan), _round_1b())
    assert decision.scope == "broad"
    assert "F2-7" in decision.fallback_reasons


def test_decide_2a_multiple_is_fixed_propagates_value_error():
    # Per spec §4.3, multiple is_fixed=True slices means structurally
    # invalid state. The route function refuses (raises ValueError) so the
    # caller — writer or CLI — surfaces a hard error rather than silently
    # falling back to broad.
    plan = [
        {"agent_id": 1, "concern": "a", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 5, "concern": "cross1", "slice_definition": "x", "is_fixed": True},
        {"agent_id": 6, "concern": "cross2", "slice_definition": "x", "is_fixed": True},
    ]
    state = _state(mode="fast", review_profile="patch")["spec"]
    with pytest.raises(ValueError, match="multiple is_fixed"):
        decide_2a(state, _round_1a(plan), _round_1b())


def test_decide_2a_multiple_fallback_reasons_aggregated_sorted_unique():
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1b = _round_1b(
        accepted=[("R1-1-001", {})],  # missing both fix_criterion and verification_target
        changelog=[{"finding_id": "R1-1-001", "change_made": "edit"}],  # no field
    )
    decision = decide_2a(state, _round_1a(plan), r1b)
    assert decision.scope == "broad"
    assert decision.fallback_reasons == ("F2-1", "F2-2")  # sorted


def test_decide_2a_cross_artifact_slice_included_when_present():
    plan = _slice_plan_plan_with_cross_artifact()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1b = _round_1b(
        accepted=[("R1-1-001", {"fix_criterion": "c", "verification_target": "t"})],
        changelog=[
            {"finding_id": "R1-1-001", "change_made": "edit", "additional_affected_slices": []},
        ],
    )
    decision = decide_2a(state, _round_1a(plan), r1b)
    assert decision.scope == "narrow"
    assert decision.selected_slices == (1, 5, 6)  # origin + global-coh + cross-artifact
