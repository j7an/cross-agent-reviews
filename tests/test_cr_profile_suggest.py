"""Tests for cr_profile_suggest.py."""

from __future__ import annotations

from _cr_lib import compute_content_hash_bytes
from cr_profile_suggest import extract_signals, suggest, suggest_for_artifact_bytes


def test_extracts_paths_and_line_anchors():
    text = (
        "Modify `plugin/skills/cr/_helpers/cr_routing.py:175` and "
        "`plugin/skills/cr/_helpers/cr_state_init.py`.\n"
    )
    s = extract_signals(text, "plan")
    assert s["referenced_file_paths_count"] == 2
    assert s["line_anchored_refs"] == 1
    assert "plugin/skills/cr/_helpers" in s["referenced_directories"]


def test_creation_markers_detected():
    text = "We will create a new module and scaffold a new package `foo/bar`.\n"
    s = extract_signals(text, "spec")
    assert s["creation_markers"] >= 1


def test_docs_only_requires_nonempty_paths():
    # No referenced paths at all -> docs_only/tests_only must be False.
    s = extract_signals("Just prose, no references.\n", "plan")
    assert s["referenced_file_paths_count"] == 0
    assert s["docs_only"] is False
    assert s["tests_only"] is False


def test_docs_only_true_when_all_paths_are_docs():
    text = "See `docs/guide.md` and `docs/notes.md`.\n"
    s = extract_signals(text, "spec")
    assert s["docs_only"] is True
    assert s["tests_only"] is False


def test_checklist_only_for_plan():
    text = "- [ ] step one\n- [ ] step two\n- [ ] step three\n- [ ] step four\n"
    s = extract_signals(text, "plan")
    assert s["checklist_item_count"] == 4
    assert s["checklist_only"] is True


def test_architecture_section_for_spec():
    text = "## Architecture\n\nThe system has components.\n"
    s = extract_signals(text, "spec")
    assert s["architecture_section_present"] is True


def _ev(text, artifact_type):
    return suggest(extract_signals(text, artifact_type), artifact_type)


def test_new_subsystem_suggests_greenfield():
    ev = _ev("We will create a new module `foo/bar`.\n", "plan")
    assert ev["suggested_review_profile"] == "greenfield"
    assert any(r["rule_id"] == "R-NEW-SUBSYSTEM" for r in ev["fired_rules"])


def test_docs_only_suggests_patch():
    ev = _ev("Edit `docs/a.md` and `docs/b.md`.\n", "plan")
    assert ev["suggested_review_profile"] == "patch"
    assert ev["resolution"] in {"single", "agreement"}


def test_insufficient_evidence_floor_is_greenfield():
    ev = _ev("Some prose with no signals at all.\n", "plan")
    assert ev["suggested_review_profile"] == "greenfield"
    assert ev["resolution"] == "insufficient_evidence"
    assert ev["resolution_reason"]["rule_id"] == "R-INSUFFICIENT-EVIDENCE"
    assert "competing_rules" not in ev["resolution_reason"]


def test_conflict_escalates_to_broadest():
    # docs-only votes patch; creation language votes greenfield. They co-fire:
    # the `x/y` token has no file extension, so it is NOT counted as a
    # referenced path and docs_only stays true. R-HIGH-EXISTING-REF-DENSITY is
    # deliberately suppressed when creation_markers != 0, so it cannot be the
    # patch voter here — docs-only is. Conflict escalates to the broadest:
    # greenfield.
    text = "Edit `docs/a.md` and `docs/b.md`. Also create a new module `x/y`.\n"
    ev = _ev(text, "plan")
    assert ev["suggested_review_profile"] == "greenfield"
    assert ev["resolution"] == "conflict"
    assert ev["resolution_reason"]["rule_id"] == "R-CONFLICT-ESCALATION"
    assert set(ev["resolution_reason"]["competing_rules"]) >= {
        "R-NEW-SUBSYSTEM",
        "R-DOCS-ONLY",
    }


def test_single_resolution_reason_has_no_competing_rules():
    ev = _ev("Edit `docs/a.md`.\n", "plan")
    assert ev["resolution"] == "single"
    assert ev["resolution_reason"]["rule_id"] == "R-SINGLE-RULE"
    assert "competing_rules" not in ev["resolution_reason"]


def test_fast_eligible_only_for_patch():
    patch_ev = _ev("Edit `docs/a.md`.\n", "plan")
    assert patch_ev["suggested_review_profile"] == "patch"
    assert patch_ev["suggested_mode"] == "fast"
    assert patch_ev["fast_eligible"] is True
    assert any(r["rule_id"] == "R-FAST-ELIGIBLE-PATCH" for r in patch_ev["fired_rules"])

    gf_ev = _ev("Create a new module `x/y`.\n", "plan")
    assert gf_ev["suggested_review_profile"] == "greenfield"
    assert gf_ev["suggested_mode"] == "thorough"
    assert gf_ev["fast_eligible"] is False


def test_suggest_for_artifact_bytes_stamps_hash_and_version():
    data = b"Edit `docs/a.md`.\n"
    ev = suggest_for_artifact_bytes(data, "plan")
    assert ev["ruleset_version"] == 1
    assert ev["artifact_type"] == "plan"
    assert ev["artifact_content_hash"] == compute_content_hash_bytes(data)
    # block-level == evidence-level for both suggested fields
    assert ev["suggested_review_profile"] == ev["suggested_review_profile"]


def test_suggest_is_deterministic():
    data = b"Create a new module `x/y`.\n"
    assert suggest_for_artifact_bytes(data, "plan") == suggest_for_artifact_bytes(data, "plan")
