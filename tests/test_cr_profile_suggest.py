"""Tests for cr_profile_suggest.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from _cr_lib import compute_content_hash_bytes
from cr_profile_suggest import _categorize, extract_signals, suggest, suggest_for_artifact_bytes

REPO_ROOT = Path(__file__).resolve().parent.parent
PS_SCRIPT = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers" / "cr_profile_suggest.py"


def _run(args, cwd):
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, str(PS_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
    )


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


def test_preview_derives_type_from_path_and_prints_json(tmp_path):
    art = tmp_path / "docs" / "specs" / "foo-design.md"
    art.parent.mkdir(parents=True)
    art.write_text("## Architecture\n\nCreate a new module `x/y`.\n")
    r = _run(["--artifact-path", str(art)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["artifact_type"] == "spec"
    assert payload["suggested_review_profile"] == "greenfield"


def test_preview_writes_no_state(tmp_path):
    art = tmp_path / "docs" / "plans" / "foo-plan.md"
    art.parent.mkdir(parents=True)
    art.write_text("- [ ] a\n- [ ] b\n- [ ] c\n")
    _run(["--artifact-path", str(art)], cwd=tmp_path)
    assert not (tmp_path / ".cross-agent-reviews").exists()


def test_preview_explicit_type_override(tmp_path):
    art = tmp_path / "ambiguous.md"
    art.write_text("Edit `docs/a.md`.\n")
    r = _run(["--artifact-path", str(art), "--artifact-type", "plan"], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["artifact_type"] == "plan"


def test_preview_undetectable_type_is_hard_error(tmp_path):
    art = tmp_path / "ambiguous.md"
    art.write_text("Edit `docs/a.md`.\n")
    r = _run(["--artifact-path", str(art)], cwd=tmp_path)
    assert r.returncode != 0
    assert "artifact-type" in r.stderr.lower()


def test_wrapper_dispatches_profile_suggest(tmp_path):
    wrapper = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers" / "cr"
    art = tmp_path / "docs" / "plans" / "foo-plan.md"
    art.parent.mkdir(parents=True)
    art.write_text("- [ ] a\n- [ ] b\n- [ ] c\n")
    r = subprocess.run(
        [str(wrapper), "profile-suggest", "--artifact-path", str(art)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["artifact_type"] == "plan"


def test_no_confidence_field_emitted():
    ev = suggest_for_artifact_bytes(b"Create a new module `x/y`.\n", "plan")
    flat = json.dumps(ev).lower()
    assert "confidence" not in flat


def test_persistence_round_trip(tmp_path):
    data = b"Edit `docs/a.md`.\n"
    ev = suggest_for_artifact_bytes(data, "plan")
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"e": ev}))
    assert json.loads(p.read_text())["e"] == ev


# --- feature-profile coverage (spec test matrix: feature-like artifacts) ---


def test_broad_fanout_suggests_feature():
    text = "Touch `src/a/one.py`, `src/b/two.py`, `src/c/three.py`, `src/d/four.py`.\n"
    ev = _ev(text, "plan")
    assert ev["suggested_review_profile"] == "feature"
    assert any(r["rule_id"] == "R-BROAD-FANOUT" for r in ev["fired_rules"])


def test_cross_artifact_deps_suggests_feature():
    text = "Implements `docs/specs/foo-design.md` and `docs/plans/bar-plan.md` via `src/impl.py`.\n"
    ev = _ev(text, "plan")
    assert ev["suggested_review_profile"] == "feature"
    assert any(r["rule_id"] == "R-CROSS-ARTIFACT-DEPS" for r in ev["fired_rules"])


def test_feature_spec_suggests_feature():
    text = "## Architecture\n\nModify `src/foo.py:10`, `src/bar.py:20`, and `src/baz.py:30`.\n"
    ev = _ev(text, "spec")
    assert ev["suggested_review_profile"] == "feature"
    assert any(r["rule_id"] == "R-FEATURE-SPEC" for r in ev["fired_rules"])


# --- categorization fixes (test-stem breadth; round_docs de-shadowing) ---


def test_test_suffix_broadened_beyond_py():
    assert _categorize("src/foo_test.go") == "tests"
    assert _categorize("pkg/bar_test.rb") == "tests"


def test_round_docs_not_shadowed_by_md_classification():
    # round-*.md must classify as round_docs, not docs (order-of-checks fix).
    assert _categorize(".cross-agent-reviews/foo/round-1a.md") == "round_docs"


# --- evidence fidelity (creation phrases; prose ratio; surfaced thresholds) ---


def test_creation_marker_phrases_recorded():
    s = extract_signals("We will create a new module `x/y`.\n", "plan")
    assert s["creation_markers"] >= 1
    assert "create a new" in s["creation_marker_phrases"]
    ev = suggest(s, "plan")
    nsub = next(r for r in ev["fired_rules"] if r["rule_id"] == "R-NEW-SUBSYSTEM")
    assert nsub["matched_signals"]["creation_marker_phrases"] == s["creation_marker_phrases"]


def test_signals_surface_requirement_prose_ratio_and_thresholds():
    s = extract_signals("Some requirement prose describing behavior.\n", "spec")
    assert s["requirement_prose_ratio"] in {"low", "med", "high"}
    assert s["thresholds"]["fanout_dirs"] == 4
    assert "checklist_min" in s["thresholds"]
