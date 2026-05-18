"""Schema files load as Draft 2020-12 and accept/reject fixtures correctly."""

import json
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_FILES = [
    "finding.schema.json",
    "verification.schema.json",
    "adjudication.schema.json",
    "changelog-entry.schema.json",
    "self-review-entry.schema.json",
    "state.schema.json",
    "round-audit.schema.json",
    "round-settle.schema.json",
    "final-verification.schema.json",
]


def load_schema(schema_dir: Path, name: str) -> dict:
    return json.loads((schema_dir / name).read_text())


def make_registry(schema_dir: Path) -> Registry:
    """Build a referencing.Registry from whichever SCHEMA_FILES exist on disk.

    Per-schema TDD: Tasks 1.2-1.7 add schemas one at a time. The registry is
    built only from the schemas already present at the current step so each
    `pytest -k <name>` green check can pass before later schemas land. Once
    all eight files exist (after Task 1.8), the registry is complete and the
    `$ref` cross-resolution exercised by `test_round_audit_passes` /
    `test_round_settle_passes` works as designed.
    """
    resources = []
    for name in SCHEMA_FILES:
        path = schema_dir / name
        if not path.exists():
            continue
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


@pytest.fixture
def registry(schema_dir):
    return make_registry(schema_dir)


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_schema_is_valid_draft_2020_12(schema_dir, name):
    schema = load_schema(schema_dir, name)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].startswith("https://j7an.github.io/cross-agent-reviews/schema/v1/")


def _validate(schema_dir, registry, schema_name, instance):
    schema = load_schema(schema_dir, schema_name)
    Draft202012Validator(schema, registry=registry).validate(instance)


def _expect_invalid(schema_dir, registry, schema_name, instance):
    with pytest.raises(jsonschema.ValidationError):
        _validate(schema_dir, registry, schema_name, instance)


# --- finding.schema.json ---


def test_finding_minimal_passes(schema_dir, registry, fixtures_dir):
    instance = json.loads((fixtures_dir / "schema_positive/finding_minimal.json").read_text())
    _validate(schema_dir, registry, "finding.schema.json", instance)


def test_finding_full_passes(schema_dir, registry, fixtures_dir):
    instance = json.loads((fixtures_dir / "schema_positive/finding_full.json").read_text())
    _validate(schema_dir, registry, "finding.schema.json", instance)


def test_finding_missing_severity_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_negative/finding_missing_severity.json").read_text()
    )
    _expect_invalid(schema_dir, registry, "finding.schema.json", instance)


def test_finding_bad_severity_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads((fixtures_dir / "schema_negative/finding_bad_severity.json").read_text())
    _expect_invalid(schema_dir, registry, "finding.schema.json", instance)


# --- verification.schema.json ---


def test_verification_resolved_passes(schema_dir, registry, fixtures_dir):
    instance = json.loads((fixtures_dir / "schema_positive/verification_resolved.json").read_text())
    _validate(schema_dir, registry, "verification.schema.json", instance)


def test_verification_bad_status_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_negative/verification_bad_status.json").read_text()
    )
    _expect_invalid(schema_dir, registry, "verification.schema.json", instance)


# --- adjudication.schema.json ---


@pytest.mark.parametrize("fixture", ["adjudication_accept.json", "adjudication_reject.json"])
def test_adjudication_passes(schema_dir, registry, fixtures_dir, fixture):
    instance = json.loads((fixtures_dir / "schema_positive" / fixture).read_text())
    _validate(schema_dir, registry, "adjudication.schema.json", instance)


def test_adjudication_bad_verdict_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_negative/adjudication_bad_verdict.json").read_text()
    )
    _expect_invalid(schema_dir, registry, "adjudication.schema.json", instance)


# --- changelog-entry, self-review-entry ---


def test_changelog_entry_passes(schema_dir, registry, fixtures_dir):
    instance = json.loads((fixtures_dir / "schema_positive/changelog_entry.json").read_text())
    _validate(schema_dir, registry, "changelog-entry.schema.json", instance)


def test_self_review_entry_passes(schema_dir, registry, fixtures_dir):
    instance = json.loads((fixtures_dir / "schema_positive/self_review_clean.json").read_text())
    _validate(schema_dir, registry, "self-review-entry.schema.json", instance)


# --- state.schema.json ---


@pytest.mark.parametrize("fixture", ["state_spec_only.json", "state_spec_and_plan.json"])
def test_state_passes(schema_dir, registry, fixtures_dir, fixture):
    instance = json.loads((fixtures_dir / "schema_positive" / fixture).read_text())
    _validate(schema_dir, registry, "state.schema.json", instance)


def test_state_bad_stage_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads((fixtures_dir / "schema_negative/state_bad_stage.json").read_text())
    _expect_invalid(schema_dir, registry, "state.schema.json", instance)


def test_state_accepts_round_3c_pending(schema_dir, registry):
    instance = {
        "schema_version": 1,
        "slug": "foo",
        "spec": {
            "path": "docs/specs/foo-design.md",
            "content_hash": "sha256:" + "a" * 64,
            "current_stage": "round_3c_pending",
            "completed_rounds": ["1a", "1b", "2a", "2b", "3a", "3b"],
            "started_at": "2026-05-16T12:00:00Z",
            "last_updated_at": "2026-05-16T12:00:00Z",
        },
    }
    _validate(schema_dir, registry, "state.schema.json", instance)


def test_state_accepts_3c_completed_round(schema_dir, registry):
    instance = {
        "schema_version": 1,
        "slug": "foo",
        "spec": {
            "path": "docs/specs/foo-design.md",
            "content_hash": "sha256:" + "a" * 64,
            "current_stage": "ready_for_implementation",
            "completed_rounds": ["1a", "1b", "2a", "2b", "3a", "3b", "3c"],
            "started_at": "2026-05-16T12:00:00Z",
            "last_updated_at": "2026-05-16T12:00:00Z",
        },
    }
    _validate(schema_dir, registry, "state.schema.json", instance)


# --- round-audit.schema.json ---


@pytest.mark.parametrize(
    "fixture",
    [
        "round_1a_audit.json",
        "round_2a_audit.json",
        "round_3a_audit.json",
    ],
)
def test_round_audit_passes(schema_dir, registry, fixtures_dir, fixture):
    instance = json.loads((fixtures_dir / "schema_positive" / fixture).read_text())
    _validate(schema_dir, registry, "round-audit.schema.json", instance)


def test_round_audit_round_stage_mismatch_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_negative/round_audit_wrong_round_for_stage.json").read_text()
    )
    _expect_invalid(schema_dir, registry, "round-audit.schema.json", instance)


# --- round-settle.schema.json ---


@pytest.mark.parametrize(
    "fixture",
    [
        "round_1b_settle.json",
        "round_3b_settle.json",
        "round_1b_settle_nit_accepted.json",
        "round_2b_settle_false_positive_accepted.json",
    ],
)
def test_round_settle_passes(schema_dir, registry, fixtures_dir, fixture):
    instance = json.loads((fixtures_dir / "schema_positive" / fixture).read_text())
    _validate(schema_dir, registry, "round-settle.schema.json", instance)


def test_round_3b_missing_final_status_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_negative/round_3b_missing_final_status.json").read_text()
    )
    _expect_invalid(schema_dir, registry, "round-settle.schema.json", instance)


# Severity gate on settle-round `accepted_findings`: only Round 3b is gated
# (the final pass is explicitly blocker-only). Rounds 1b and 2b inherit the
# full Finding severity enum — each round's *audit* stage already controls
# which severities can be produced, so the settle round does not re-gate
# them. The fixture below embeds one accepted non-blocker (`gap`) finding in
# an otherwise schema-valid 3b envelope, so a failure here pinpoints a
# missing or incorrect 3b `allOf` clause.
def test_round_3b_settle_nonblocker_accepted_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_negative/round_3b_settle_nonblocker_accepted.json").read_text()
    )
    _expect_invalid(schema_dir, registry, "round-settle.schema.json", instance)


def test_round_3b_zero_accepted_requires_ready(schema_dir, registry, fixtures_dir):
    """3b with empty accepted_findings MUST carry final_status READY_FOR_IMPLEMENTATION."""
    instance = json.loads((fixtures_dir / "schema_positive/round_3b_settle.json").read_text())
    assert instance["accepted_findings"] == []
    assert instance["final_status"] == "READY_FOR_IMPLEMENTATION"
    _validate(schema_dir, registry, "round-settle.schema.json", instance)


def test_round_3b_zero_accepted_with_cpv_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads((fixtures_dir / "schema_positive/round_3b_settle.json").read_text())
    instance["final_status"] = "CORRECTED_PENDING_VERIFICATION"
    _expect_invalid(schema_dir, registry, "round-settle.schema.json", instance)


def test_round_3b_accepted_with_cpv_passes(schema_dir, registry, fixtures_dir):
    """A 3b with accepted findings is valid ONLY with CORRECTED_PENDING_VERIFICATION."""
    instance = json.loads(
        (fixtures_dir / "schema_positive/round_3b_settle_corrected.json").read_text()
    )
    assert instance["accepted_findings"]  # non-empty
    assert instance["final_status"] == "CORRECTED_PENDING_VERIFICATION"
    _validate(schema_dir, registry, "round-settle.schema.json", instance)


def test_round_3b_accepted_with_ready_fails(schema_dir, registry, fixtures_dir):
    """Requirement-9 gate: accepted findings + READY_FOR_IMPLEMENTATION is REJECTED
    — a paste cannot present corrected 3b work as ready without verification."""
    instance = json.loads(
        (fixtures_dir / "schema_positive/round_3b_settle_corrected.json").read_text()
    )
    instance["final_status"] = "READY_FOR_IMPLEMENTATION"
    _expect_invalid(schema_dir, registry, "round-settle.schema.json", instance)


def test_round_3b_corrected_and_ready_value_removed(schema_dir, registry, fixtures_dir):
    """CORRECTED_AND_READY is no longer a legal settle-round final_status."""
    instance = json.loads((fixtures_dir / "schema_positive/round_3b_settle.json").read_text())
    instance["final_status"] = "CORRECTED_AND_READY"
    _expect_invalid(schema_dir, registry, "round-settle.schema.json", instance)


# --- final-verification.schema.json ---


def test_final_verification_passed_passes(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_positive/final_verification_passed.json").read_text()
    )
    _validate(schema_dir, registry, "final-verification.schema.json", instance)


def test_final_verification_passed_with_unresolved_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_negative/final_verification_passed_unresolved.json").read_text()
    )
    _expect_invalid(schema_dir, registry, "final-verification.schema.json", instance)


def test_final_verification_failed_must_omit_final_status(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_positive/final_verification_passed.json").read_text()
    )
    instance["result"] = "failed"
    instance["verifications"] = [
        {"round_3a_finding_id": "R3-1-001", "status": "not_resolved", "evidence": "x"}
    ]
    # final_status still present -> invalid for a failed envelope
    _expect_invalid(schema_dir, registry, "final-verification.schema.json", instance)


def test_final_verification_passed_with_regression_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_positive/final_verification_passed.json").read_text()
    )
    instance["regression_findings"] = [
        {
            "id": "R3C-001",
            "location": "§6",
            "severity": "blocker",
            "finding": "edit broke the cross-reference",
            "why_it_matters": "implementer follows a dead link",
            "suggested_direction": "repoint the reference",
        }
    ]
    _expect_invalid(schema_dir, registry, "final-verification.schema.json", instance)


def test_final_verification_bad_regression_id_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_positive/final_verification_passed.json").read_text()
    )
    instance["result"] = "failed"
    del instance["final_status"]
    instance["regression_findings"] = [
        {
            "id": "R3-1-001",
            "location": "§6",
            "severity": "blocker",
            "finding": "x",
            "why_it_matters": "y",
            "suggested_direction": "z",
        }
    ]
    _expect_invalid(schema_dir, registry, "final-verification.schema.json", instance)


def test_final_verification_missing_prior_attempts_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_positive/final_verification_passed.json").read_text()
    )
    del instance["prior_attempts"]
    _expect_invalid(schema_dir, registry, "final-verification.schema.json", instance)


def test_final_verification_bad_finding_id_fails(schema_dir, registry, fixtures_dir):
    instance = json.loads(
        (fixtures_dir / "schema_positive/final_verification_passed.json").read_text()
    )
    instance["verifications"][0]["round_3a_finding_id"] = "R3-9-001"
    _expect_invalid(schema_dir, registry, "final-verification.schema.json", instance)


# --- state.schema.json: mode and review_profile fields ---


def _base_state():
    return {
        "schema_version": 1,
        "slug": "foo",
        "spec": {
            "path": "docs/specs/foo-design.md",
            "content_hash": "sha256:" + "0" * 64,
            "current_stage": "round_1a_pending",
            "completed_rounds": [],
            "started_at": "2026-05-17T10:00:00Z",
            "last_updated_at": "2026-05-17T10:00:00Z",
        },
    }


def test_state_legacy_without_mode_profile_valid(schema_dir, registry):
    _validate(schema_dir, registry, "state.schema.json", _base_state())


def test_state_accepts_mode_and_review_profile(schema_dir, registry):
    state = _base_state()
    state["spec"]["mode"] = "fast"
    state["spec"]["review_profile"] = "patch"
    _validate(schema_dir, registry, "state.schema.json", state)


def test_state_rejects_bad_mode(schema_dir, registry):
    state = _base_state()
    state["spec"]["mode"] = "turbo"
    _expect_invalid(schema_dir, registry, "state.schema.json", state)


def test_state_rejects_bad_review_profile(schema_dir, registry):
    state = _base_state()
    state["spec"]["review_profile"] = "huge"
    _expect_invalid(schema_dir, registry, "state.schema.json", state)


def test_state_accepts_mode_and_review_profile_on_plan(schema_dir, registry):
    state = _base_state()
    state["spec"]["current_stage"] = "ready_for_implementation"
    state["spec"]["completed_rounds"] = ["1a", "1b", "2a", "2b", "3a", "3b"]
    state["plan"] = {
        "path": "docs/plans/foo-plan.md",
        "content_hash": "sha256:" + "b" * 64,
        "spec_hash_at_start": "sha256:" + "0" * 64,
        "current_stage": "round_1a_pending",
        "completed_rounds": [],
        "started_at": "2026-05-17T10:00:00Z",
        "last_updated_at": "2026-05-17T10:00:00Z",
        "mode": "fast",
        "review_profile": "patch",
    }
    _validate(schema_dir, registry, "state.schema.json", state)
