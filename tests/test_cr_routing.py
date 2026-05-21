"""Tests for cr_routing.identify_mandatory_slices + RouteDecision dataclass."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from cr_routing import RouteDecision, decide_2a, decide_3a, identify_mandatory_slices


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


def _round_2a(*, agents=None):
    """Minimal 2a envelope. `agents` is a list of dicts with
    agent_id + status + findings + round_1_verifications."""
    return {"stage": "2a", "slice_plan": [], "agents": agents or []}


def _round_2b(*, accepted=(), changelog=(), finding_lineage=()):
    """2b envelope with optional finding_lineage."""
    env = {
        "stage": "2b",
        "slice_plan": [],
        "adjudications": [
            {"finding_id": fid, "verdict": "accept", "reasoning": "ok", **extras}
            for fid, extras in accepted
        ],
        "accepted_findings": [
            {"id": fid, "severity": extras.get("_severity", "gap")} for fid, extras in accepted
        ],
        "rejected_findings": [],
        "changelog": list(changelog),
        "self_review": [],
    }
    if finding_lineage:
        env["finding_lineage"] = list(finding_lineage)
    return env


def _lineage(
    *,
    lineage_id,
    original_finding_id,
    originating_agent_id,
    affected_slices=(1,),
    originating_stage="1a",
    latest_verification=None,
    prior_lineage_id=None,
    fix_criterion="c",
    verification_target="t",
):
    return {
        "lineage_id": lineage_id,
        "original_finding_id": original_finding_id,
        "originating_stage": originating_stage,
        "originating_agent_id": originating_agent_id,
        "originating_slice": "x",
        "affected_location": "y",
        "affected_slices": list(affected_slices),
        "fix_criterion": fix_criterion,
        "verification_target": verification_target,
        "prior_lineage_id": prior_lineage_id,
        "latest_verification": latest_verification,
    }


def test_decide_3a_patch_fast_complete_lineage_narrow():
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1a = _round_1a(plan)
    r1b = _round_1b()
    r2a = _round_2a(
        agents=[
            {
                "agent_id": 1,
                "status": "verified",
                "findings": [],
                "round_1_verifications": [
                    {"round_1_finding_id": "R1-1-001", "status": "resolved", "evidence": "x"}
                ],
            },
        ]
    )
    lineage = [
        _lineage(
            lineage_id="L-2b-R1-1-001",
            original_finding_id="R1-1-001",
            originating_agent_id=1,
            affected_slices=[1, 3],
            latest_verification={"status": "resolved", "evidence": "x"},
            prior_lineage_id="L-1b-R1-1-001",
        ),
    ]
    r2b = _round_2b(finding_lineage=lineage)
    decision = decide_3a(state, r1a, r1b, r2a, r2b)
    assert decision.scope == "narrow"
    assert decision.selected_slices == (1, 3, 5)


def test_decide_3a_feature_fast_always_broad_F3_2():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="feature")["spec"]
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), _round_2b())
    assert decision.scope == "broad"
    assert "F3-2" in decision.fallback_reasons


def test_decide_3a_patch_thorough_falls_back_F3_2():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="thorough", review_profile="patch")["spec"]
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), _round_2b())
    assert decision.scope == "broad"
    assert "F3-2" in decision.fallback_reasons


def test_decide_3a_not_resolved_verification_falls_back_F3_3():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r2a = _round_2a(
        agents=[
            {
                "agent_id": 1,
                "status": "issues_found",
                "findings": [],
                "round_1_verifications": [
                    {"round_1_finding_id": "R1-1-001", "status": "not_resolved", "evidence": "x"}
                ],
            },
        ]
    )
    lineage = [
        _lineage(
            lineage_id="L-2b-R1-1-001",
            original_finding_id="R1-1-001",
            originating_agent_id=1,
            latest_verification={"status": "not_resolved", "evidence": "x"},
            prior_lineage_id="L-1b-R1-1-001",
        ),
    ]
    r2b = _round_2b(finding_lineage=lineage)
    decision = decide_3a(state, _round_1a(plan), _round_1b(), r2a, r2b)
    assert decision.scope == "broad"
    assert "F3-3" in decision.fallback_reasons


def test_decide_3a_accepted_2a_blocker_falls_back_F3_4():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r2b = _round_2b(
        accepted=[
            ("R2-1-001", {"_severity": "blocker", "fix_criterion": "c", "verification_target": "t"})
        ],
        changelog=[
            {"finding_id": "R2-1-001", "change_made": "edit", "additional_affected_slices": []}
        ],
        finding_lineage=[
            _lineage(
                lineage_id="L-2b-R2-1-001",
                original_finding_id="R2-1-001",
                originating_agent_id=1,
                originating_stage="2a",
                latest_verification=None,
            ),
        ],
    )
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), r2b)
    assert decision.scope == "broad"
    assert "F3-4" in decision.fallback_reasons


def test_decide_3a_accepted_2a_gap_does_not_trigger_fallback():
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r2b = _round_2b(
        accepted=[
            ("R2-1-001", {"_severity": "gap", "fix_criterion": "c", "verification_target": "t"})
        ],
        changelog=[
            {"finding_id": "R2-1-001", "change_made": "edit", "additional_affected_slices": [3]}
        ],
        finding_lineage=[
            _lineage(
                lineage_id="L-2b-R2-1-001",
                original_finding_id="R2-1-001",
                originating_agent_id=1,
                originating_stage="2a",
                affected_slices=[1, 3],
                latest_verification=None,
            ),
        ],
    )
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), r2b)
    assert decision.scope == "narrow"
    assert decision.selected_slices == (1, 3, 5)


def test_decide_3a_missing_carry_forward_falls_back_F3_5():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    # 1a accepted finding R1-1-001 -> 1b lineage row L-1b-R1-1-001
    r1b = _round_1b(
        accepted=[("R1-1-001", {"fix_criterion": "c", "verification_target": "t"})],
        changelog=[
            {"finding_id": "R1-1-001", "change_made": "edit", "additional_affected_slices": []}
        ],
    )
    r1b["finding_lineage"] = [
        _lineage(
            lineage_id="L-1b-R1-1-001",
            original_finding_id="R1-1-001",
            originating_agent_id=1,
            latest_verification=None,
        ),
    ]
    # 2b is missing the carry-forward
    r2b = _round_2b(finding_lineage=[])
    decision = decide_3a(state, _round_1a(plan), r1b, _round_2a(), r2b)
    assert decision.scope == "broad"
    assert "F3-5" in decision.fallback_reasons


def test_decide_3a_carry_forward_missing_latest_verification_falls_back_F3_5():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r2b = _round_2b(
        finding_lineage=[
            _lineage(
                lineage_id="L-2b-R1-1-001",
                original_finding_id="R1-1-001",
                originating_agent_id=1,
                originating_stage="1a",
                latest_verification=None,
                prior_lineage_id="L-1b-R1-1-001",
            ),
        ]
    )
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), r2b)
    assert decision.scope == "broad"
    assert "F3-5" in decision.fallback_reasons


def test_decide_3a_accepted_1b_finding_without_lineage_falls_back_F3_5():  # noqa: N802
    # Fail-closed: if 1b accepted a finding but no lineage row was emitted for
    # it (writer best-effort skip on LINEAGE_INCOMPLETE), decide_3a must fall
    # back broad. Otherwise narrow 3a can skip slices that Round 1 edited.
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1b = _round_1b(
        accepted=[
            ("R1-1-001", {"fix_criterion": "c", "verification_target": "t"}),
        ],
        changelog=[
            {"finding_id": "R1-1-001", "change_made": "edit", "additional_affected_slices": [3]},
        ],
    )
    # writer skipped 1b lineage row emission for R1-1-001 (finding_lineage absent).
    r2b = _round_2b(finding_lineage=[])
    decision = decide_3a(state, _round_1a(plan), r1b, _round_2a(), r2b)
    assert decision.scope == "broad"
    assert "F3-5" in decision.fallback_reasons


def test_decide_3a_accepted_2a_finding_without_2b_lineage_falls_back_F3_5():  # noqa: N802
    # Fail-closed: if 2b accepted a Round 2 finding but no fresh 2b lineage
    # row was emitted for it (writer best-effort skip on LINEAGE_INCOMPLETE),
    # decide_3a must fall back broad. Otherwise narrow 3a can skip the slice
    # the author edited to fix the 2a finding.
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r2b = _round_2b(
        accepted=[
            ("R2-2-001", {"_severity": "gap", "fix_criterion": "c", "verification_target": "t"}),
        ],
        changelog=[
            {"finding_id": "R2-2-001", "change_made": "edit", "additional_affected_slices": [3]},
        ],
        # writer skipped 2b lineage row emission for R2-2-001.
        finding_lineage=[],
    )
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), r2b)
    assert decision.scope == "broad"
    assert "F3-5" in decision.fallback_reasons


def test_decide_3a_carry_forward_dropping_affected_slice_falls_back_F3_5():  # noqa: N802
    # Defensive: a 2b carry-forward row must preserve the 1b row's
    # affected_slices. Shrinking the set (e.g., via paste-import or hand
    # edit) would silently drop a slice Round 1 actually edited.
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r1b = _round_1b(
        accepted=[("R1-1-001", {"fix_criterion": "c", "verification_target": "t"})],
        changelog=[
            {"finding_id": "R1-1-001", "change_made": "edit", "additional_affected_slices": [3]},
        ],
    )
    r1b["finding_lineage"] = [
        _lineage(
            lineage_id="L-1b-R1-1-001",
            original_finding_id="R1-1-001",
            originating_agent_id=1,
            affected_slices=[1, 3],
            latest_verification=None,
        ),
    ]
    r2a = _round_2a(
        agents=[
            {
                "agent_id": 1,
                "status": "verified",
                "findings": [],
                "round_1_verifications": [
                    {"round_1_finding_id": "R1-1-001", "status": "resolved", "evidence": "x"}
                ],
            },
        ]
    )
    r2b = _round_2b(
        finding_lineage=[
            _lineage(
                lineage_id="L-2b-R1-1-001",
                original_finding_id="R1-1-001",
                originating_agent_id=1,
                # 1b said [1, 3] — carry-forward dropped slice 3.
                affected_slices=[1],
                latest_verification={"status": "resolved", "evidence": "x"},
                prior_lineage_id="L-1b-R1-1-001",
            ),
        ]
    )
    decision = decide_3a(state, _round_1a(plan), r1b, r2a, r2b)
    assert decision.scope == "broad"
    assert "F3-5" in decision.fallback_reasons


def test_decide_3a_inherits_F2_like_reasons_as_F3_1():  # noqa: N802
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    # 2b adjudication missing fix_criterion -> would be F2-1 on a 2a decision;
    # surfaces as F3-1 on a 3a decision.
    r2b = _round_2b(
        accepted=[("R2-1-001", {"_severity": "gap"})],
        changelog=[
            {"finding_id": "R2-1-001", "change_made": "edit", "additional_affected_slices": []}
        ],
    )
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), r2b)
    assert decision.scope == "broad"
    assert "F3-1" in decision.fallback_reasons


def test_decide_3a_multiple_is_fixed_propagates_value_error():
    plan = [
        {"agent_id": 1, "concern": "a", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 5, "concern": "cross1", "slice_definition": "x", "is_fixed": True},
        {"agent_id": 6, "concern": "cross2", "slice_definition": "x", "is_fixed": True},
    ]
    state = _state(mode="fast", review_profile="patch")["spec"]
    with pytest.raises(ValueError, match="multiple is_fixed"):
        decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), _round_2b())


def test_decide_3a_fresh_2a_lineage_shrinks_affected_slices_falls_back_F3_5():  # noqa: N802
    # Defensive: a fresh (originating_stage=2a) lineage row's affected_slices
    # must equal the set union of {origin_agent_id} and changelog
    # .additional_affected_slices. A paste-imported or hand-edited 2b that
    # shrinks the set would silently skip a slice the author declared affected.
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r2b = _round_2b(
        accepted=[
            ("R2-1-001", {"_severity": "gap", "fix_criterion": "c", "verification_target": "t"}),
        ],
        changelog=[
            {"finding_id": "R2-1-001", "change_made": "edit", "additional_affected_slices": [3]},
        ],
        finding_lineage=[
            _lineage(
                lineage_id="L-2b-R2-1-001",
                original_finding_id="R2-1-001",
                originating_agent_id=1,
                originating_stage="2a",
                # changelog declared {1, 3}; row shrinks to {1}.
                affected_slices=[1],
                latest_verification=None,
            ),
        ],
    )
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), r2b)
    assert decision.scope == "broad"
    assert "F3-5" in decision.fallback_reasons


def test_identify_mandatory_slices_duplicate_highest_non_fixed_is_undetectable():
    # Schema does not enforce agent_id uniqueness across slice_plan entries.
    # When the highest non-fixed agent_id appears more than once, the
    # global-coherence slice is ambiguous; identify_mandatory_slices must
    # signal undetectable so callers fall back broad (F2-7 / F3-1).
    plan = [
        {"agent_id": 1, "concern": "a", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 5, "concern": "global1", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 5, "concern": "global2", "slice_definition": "x", "is_fixed": False},
    ]
    result = identify_mandatory_slices(plan)
    assert result["global_coherence_slice"] is None
    assert result["cross_artifact_slice"] is None


def test_decide_2a_duplicate_highest_non_fixed_falls_back_F2_7():  # noqa: N802
    plan = [
        {"agent_id": 1, "concern": "a", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 5, "concern": "global1", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 5, "concern": "global2", "slice_definition": "x", "is_fixed": False},
    ]
    state = _state(mode="fast", review_profile="patch")["spec"]
    decision = decide_2a(state, _round_1a(plan), _round_1b())
    assert decision.scope == "broad"
    assert "F2-7" in decision.fallback_reasons
    # And _broad() must dedupe selected_slices when the plan contains
    # duplicate agent_ids.
    assert decision.selected_slices == (1, 5)


def test_decide_3a_duplicate_highest_non_fixed_falls_back_F3_1():  # noqa: N802
    plan = [
        {"agent_id": 1, "concern": "a", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 5, "concern": "global1", "slice_definition": "x", "is_fixed": False},
        {"agent_id": 5, "concern": "global2", "slice_definition": "x", "is_fixed": False},
    ]
    state = _state(mode="fast", review_profile="patch")["spec"]
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), _round_2b())
    assert decision.scope == "broad"
    assert "F3-1" in decision.fallback_reasons
    assert decision.selected_slices == (1, 5)


def test_decide_3a_rejected_2a_finding_does_not_expand_scope():
    plan = _slice_plan_spec()
    state = _state(mode="fast", review_profile="patch")["spec"]
    r2b = _round_2b(
        finding_lineage=[
            _lineage(
                lineage_id="L-2b-R1-1-001",
                original_finding_id="R1-1-001",
                originating_agent_id=1,
                affected_slices=[1],
                latest_verification={"status": "resolved", "evidence": "x"},
                prior_lineage_id="L-1b-R1-1-001",
            ),
        ]
    )
    # Add a rejected 2a finding via adjudications -> no entry in
    # accepted_findings, no lineage row. Scope stays at lineage's slices.
    r2b["adjudications"].append(
        {"finding_id": "R2-2-001", "verdict": "reject", "reasoning": "false positive"}
    )
    r2b["rejected_findings"].append({"id": "R2-2-001", "severity": "gap"})
    decision = decide_3a(state, _round_1a(plan), _round_1b(), _round_2a(), r2b)
    assert decision.scope == "narrow"
    assert decision.selected_slices == (1, 5)
