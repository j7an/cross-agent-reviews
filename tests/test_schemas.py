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
