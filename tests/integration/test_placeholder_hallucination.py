"""End-to-end: spec with a placeholder + plan with hallucinated literal → blocker emerges from the cross-artifact slice."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXTRACT = REPO_ROOT / "scripts" / "cr_extract_placeholders.py"


def test_hallucinated_literal_is_visible_in_extractor_report(tmp_path):
    spec = tmp_path / "foo-design.md"
    plan = tmp_path / "foo-plan.md"
    shutil.copy(REPO_ROOT / "tests/fixtures/spec_plan_pairs/hallucinated/spec.md", spec)
    shutil.copy(REPO_ROOT / "tests/fixtures/spec_plan_pairs/hallucinated/plan.md", plan)
    result = subprocess.run(
        [sys.executable, str(EXTRACT), "--spec-path", str(spec), "--plan-path", str(plan)],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    out = json.loads(result.stdout)
    placeholder = out["spec_placeholders"][0]
    correspondence = placeholder["plan_correspondence"]
    # The script's job is to surface the hallucinated literal so the LLM sub-agent
    # can classify it. Acceptance criterion #2: the substituted literal appears,
    # is_substituted is True, has_inline_citation is False, is_flagged_unverified is False.
    assert correspondence["found"] is True
    assert correspondence["is_substituted"] is True
    assert correspondence["has_inline_citation"] is False
    assert correspondence["is_flagged_unverified"] is False
    assert "12345678" in correspondence["literal"]


def test_round_1a_blocker_envelope_with_cross_artifact_slice_validates(tmp_path):
    """Acceptance criterion #2 (§15) requires that the Round 1a cross-artifact
    slice produces a *blocker* on a hallucinated literal — not just that the
    extractor surfaces the fields. The classifier is the LLM sub-agent's job
    (un-testable here), but we can fix the classifier's deterministic
    output and verify the resulting Round 1a audit envelope passes schema
    validation. If the schema rejected this shape, the cross-artifact path
    would be broken even with a perfect classifier."""
    schema_dir = REPO_ROOT / "plugin" / "skills" / "cr" / "_shared" / "schema"
    audit_schema = json.loads((schema_dir / "round-audit.schema.json").read_text())
    # Build the canonical 1a envelope a real run would produce: 5 internal
    # slices (4 clean + 1 example with a regular blocker) plus the fixed
    # cross-artifact slice (agent_id 6) emitting one BLOCKER for the
    # hallucinated literal per the cross-artifact-slice.md rubric.
    envelope = {
        "round": 1,
        "stage": "1a",
        "schema_version": 1,
        "slug": "foo",
        "artifact_type": "plan",
        "artifact_path": "docs/plans/foo-plan.md",
        "emitted_at": "2026-05-07T12:00:00Z",
        "slice_plan": [
            {"agent_id": 1, "concern": "Phase A", "slice_definition": "Phase 0", "is_fixed": False},
            {"agent_id": 2, "concern": "Phase B", "slice_definition": "Phase 1", "is_fixed": False},
            {"agent_id": 3, "concern": "Phase C", "slice_definition": "Phase 2", "is_fixed": False},
            {"agent_id": 4, "concern": "Phase D", "slice_definition": "Phase 3", "is_fixed": False},
            {
                "agent_id": 5,
                "concern": "Cross-cutting",
                "slice_definition": "all",
                "is_fixed": False,
            },
            {
                "agent_id": 6,
                "concern": "Cross-artifact",
                "slice_definition": "spec/plan parity",
                "is_fixed": True,
            },
        ],
        "agents": [
            {
                "agent_id": 1,
                "concern": "Phase A",
                "slice_definition": "Phase 0",
                "status": "clean",
                "findings": [],
                "round_1_verifications": [],
            },
            {
                "agent_id": 2,
                "concern": "Phase B",
                "slice_definition": "Phase 1",
                "status": "clean",
                "findings": [],
                "round_1_verifications": [],
            },
            {
                "agent_id": 3,
                "concern": "Phase C",
                "slice_definition": "Phase 2",
                "status": "clean",
                "findings": [],
                "round_1_verifications": [],
            },
            {
                "agent_id": 4,
                "concern": "Phase D",
                "slice_definition": "Phase 3",
                "status": "clean",
                "findings": [],
                "round_1_verifications": [],
            },
            {
                "agent_id": 5,
                "concern": "Cross-cutting",
                "slice_definition": "all",
                "status": "clean",
                "findings": [],
                "round_1_verifications": [],
            },
            {
                "agent_id": 6,
                "concern": "Cross-artifact",
                "slice_definition": "spec/plan parity",
                "status": "findings_found",
                "findings": [
                    {
                        "id": "R1-6-001",
                        "location": "plan line 4 (corresponds to spec line 3)",
                        "severity": "blocker",
                        "finding": "Plan substitutes hallucinated literal '12345678' for spec placeholder '<numeric-id>'",
                        "why_it_matters": "Implementer would commit a fabricated UID; CLAUDE.md placeholder-substitution rule.",
                        "suggested_direction": "Restore the placeholder OR cite a primary source OR flag <unverified>.",
                    }
                ],
                "round_1_verifications": [],
            },
        ],
    }
    from jsonschema import Draft202012Validator

    from scripts._cr_lib import build_registry, find_repo_root

    registry = build_registry(find_repo_root(REPO_ROOT))
    Draft202012Validator(audit_schema, registry=registry).validate(envelope)
    blockers = [f for a in envelope["agents"] for f in a["findings"] if f["severity"] == "blocker"]
    assert any(f["id"].startswith("R1-6-") for f in blockers), (
        "the cross-artifact slice (agent_id 6) MUST be the source of at least one blocker"
    )


def test_round_1a_rejects_non_blocker_finding_from_agent_6():
    """Acceptance criterion #2 enforcement: the cross-artifact-slice rubric
    promises non-blocker findings from agent_id 6 are rejected. The
    round-audit schema's `if agent_id == 6 then severity == blocker` clause
    is what makes that promise auditable. Without this test, the agent-6
    constraint could be quietly removed or never added and the rubric's
    enforcement claim would silently lapse."""
    import jsonschema
    from jsonschema import Draft202012Validator

    from scripts._cr_lib import build_registry, find_repo_root

    schema_dir = REPO_ROOT / "plugin" / "skills" / "cr" / "_shared" / "schema"
    audit_schema = json.loads((schema_dir / "round-audit.schema.json").read_text())
    registry = build_registry(find_repo_root(REPO_ROOT))
    envelope = {
        "round": 1,
        "stage": "1a",
        "schema_version": 1,
        "slug": "foo",
        "artifact_type": "plan",
        "artifact_path": "docs/plans/foo-plan.md",
        "emitted_at": "2026-05-07T12:00:00Z",
        "slice_plan": [
            {"agent_id": 1, "concern": "X", "slice_definition": "X", "is_fixed": False},
            {
                "agent_id": 6,
                "concern": "Cross-artifact",
                "slice_definition": "spec/plan parity",
                "is_fixed": True,
            },
        ],
        "agents": [
            {
                "agent_id": 1,
                "concern": "X",
                "slice_definition": "X",
                "status": "clean",
                "findings": [],
                "round_1_verifications": [],
            },
            {
                "agent_id": 6,
                "concern": "Cross-artifact",
                "slice_definition": "spec/plan parity",
                "status": "findings_found",
                "findings": [
                    {
                        "id": "R1-6-001",
                        "location": "plan line 4",
                        "severity": "gap",  # NOT blocker — must be rejected
                        "finding": "Plan substitutes a value with weak provenance.",
                        "why_it_matters": "Agent 6 is permitted to emit only blockers per the rubric.",
                        "suggested_direction": "Use blocker severity, or reject as not a hallucination.",
                    }
                ],
                "round_1_verifications": [],
            },
        ],
    }
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(audit_schema, registry=registry).validate(envelope)
