"""Tests for cr_routing.identify_mandatory_slices + RouteDecision dataclass."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from cr_routing import RouteDecision, identify_mandatory_slices


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
