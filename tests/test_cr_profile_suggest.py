"""Tests for cr_profile_suggest.py."""

from __future__ import annotations

from cr_profile_suggest import extract_signals


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
