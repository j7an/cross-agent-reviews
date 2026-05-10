"""Tests for cr_extract_placeholders.py."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers" / "cr_extract_placeholders.py"


def run(args, cwd=REPO_ROOT, stdin=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )


@pytest.fixture
def pairs_dir(fixtures_dir):
    return fixtures_dir / "spec_plan_pairs"


def _extract(pairs_dir, name):
    spec = pairs_dir / name / "spec.md"
    plan = pairs_dir / name / "plan.md"
    result = run(["--spec-path", str(spec), "--plan-path", str(plan)])
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_preserved_pair(pairs_dir):
    out = _extract(pairs_dir, "preserved")
    placeholders = out["spec_placeholders"]
    assert len(placeholders) == 1
    p = placeholders[0]
    assert p["pattern_kind"] == "angle-bracket"
    assert p["plan_correspondence"]["found"] is True
    assert p["plan_correspondence"]["multiple_candidates"] is False
    # `literal` is the full corresponding plan line (the script does not
    # extract a substring); preservation is signalled by `is_substituted`
    # being False because the spec placeholder appears verbatim in the line.
    assert "<numeric-id>" in p["plan_correspondence"]["literal"]
    assert p["plan_correspondence"]["is_substituted"] is False


def test_hallucinated_pair_is_substituted(pairs_dir):
    out = _extract(pairs_dir, "hallucinated")
    p = out["spec_placeholders"][0]
    # Plan replaced `<numeric-id>` with a concrete UID, so `is_substituted`
    # MUST be True. This is the load-bearing flag for the cross-artifact
    # rubric's hallucinated-literal classification.
    assert p["plan_correspondence"]["is_substituted"] is True


def test_hallucinated_pair(pairs_dir):
    out = _extract(pairs_dir, "hallucinated")
    p = out["spec_placeholders"][0]
    assert p["plan_correspondence"]["found"] is True
    # The plan substitutes a literal — we report what we see; classification is the LLM's job.
    assert "12345678" in p["plan_correspondence"]["literal"]


def test_cited_pair(pairs_dir):
    out = _extract(pairs_dir, "cited")
    p = out["spec_placeholders"][0]
    assert p["plan_correspondence"]["found"] is True
    assert p["plan_correspondence"]["has_inline_citation"] is True


def test_unverified_text_is_not_a_citation(tmp_path):
    """Regression: `_has_citation` previously matched the substring `verified`
    inside `unverified`, mis-classifying the explicit "needs lookup" marker as
    a citation and silently passing hallucinated literals through the
    cross-artifact rubric. Word-boundary matching plus an `_is_unverified_flag`
    short-circuit fixes it."""
    spec = tmp_path / "spec.md"
    plan = tmp_path / "plan.md"
    spec.write_text("The user UID `<numeric-id>` is a placeholder.\n")
    # Plan line shares enough anchor tokens with the spec line ({The, user,
    # UID, placeholder}) to clear the JACCARD_THRESHOLD (0.6) — the shorter
    # `<unverified>` literal keeps the unique plan-token count low so
    # correspondence resolves to `found: True` and the citation/unverified
    # fields are present on the response.
    plan.write_text("The user UID `<unverified>` is a placeholder.\n")
    result = run(["--spec-path", str(spec), "--plan-path", str(plan)])
    out = json.loads(result.stdout)
    p = out["spec_placeholders"][0]
    # The plan line contains "unverified" but does NOT contain a real citation.
    # `has_inline_citation` MUST be False; `is_flagged_unverified` MUST be True.
    assert p["plan_correspondence"]["found"] is True
    assert p["plan_correspondence"]["has_inline_citation"] is False
    assert p["plan_correspondence"]["is_flagged_unverified"] is True


def test_verified_prose_is_classified_as_citation(tmp_path):
    """Documents the limit of `_has_citation`: a positive `verified` line IS
    classified as a citation by the script (the `\\bverified\\b` word-boundary
    match fires). The script does NOT detect arbitrary negated forms like
    `not verified` — that judgment is delegated to the LLM sub-agent per the
    cross-artifact-slice.md rubric. The `_is_unverified_flag` short-circuit
    only protects against the `unverified` substring trap (covered by
    `test_unverified_text_is_not_a_citation`); negated prose is out of scope
    for this script."""
    spec = tmp_path / "spec.md"
    plan = tmp_path / "plan.md"
    spec.write_text("The user UID `<numeric-id>` is a placeholder.\n")
    # Plan line shares enough anchor tokens with the spec line ({The, user,
    # UID, placeholder}) to clear the JACCARD_THRESHOLD (0.6); kept short so
    # the correspondence resolves and the citation-bearing fields are
    # present on the response.
    plan.write_text("The user UID is a placeholder, verified.\n")
    result = run(["--spec-path", str(spec), "--plan-path", str(plan)])
    out = json.loads(result.stdout)
    p = out["spec_placeholders"][0]
    # Genuinely citation-bearing line: should be flagged as cited.
    assert p["plan_correspondence"]["found"] is True
    assert p["plan_correspondence"]["has_inline_citation"] is True


def test_multi_candidate(pairs_dir):
    out = _extract(pairs_dir, "multi_candidate")
    p = out["spec_placeholders"][0]
    assert p["plan_correspondence"]["multiple_candidates"] is True
    assert len(p["plan_correspondence"]["candidates"]) == 2


def test_zero_candidate(pairs_dir):
    out = _extract(pairs_dir, "zero_candidate")
    p = out["spec_placeholders"][0]
    assert p["plan_correspondence"]["found"] is False
    assert p["plan_correspondence"]["unmatched_reason"] == "no_plan_line_above_threshold"


def test_plan_only_concrete_values_emitted(pairs_dir):
    out = _extract(pairs_dir, "plan_only_concrete")
    plan_only = out["plan_only_concrete_values"]
    kinds = {item["kind"] for item in plan_only}
    assert "version-pin" in kinds
    assert "port" in kinds


def test_pattern_kinds_detected(pairs_dir, tmp_path):
    spec = tmp_path / "spec.md"
    plan = tmp_path / "plan.md"
    spec.write_text(
        "Angle bracket: `<foo>`\n"
        "Template var: `${BAR}`\n"
        "Double underscore: `__BAZ__`\n"
        "User token: `<your-name>`\n"
        "TODO: implement TODO logic\n"
        "Unverified: `<unverified — needs lookup: gh api users/me>`\n"
    )
    plan.write_text("Plan content unrelated.\n")
    result = run(["--spec-path", str(spec), "--plan-path", str(plan)])
    out = json.loads(result.stdout)
    kinds = {p["pattern_kind"] for p in out["spec_placeholders"]}
    assert "angle-bracket" in kinds
    assert "template-var" in kinds
    assert "double-underscore" in kinds
    assert "user-token" in kinds
    assert "todo-marker" in kinds
    assert "unverified-marker" in kinds


def test_spec_path_not_found(tmp_path):
    result = run(
        ["--spec-path", str(tmp_path / "missing.md"), "--plan-path", str(tmp_path / "missing2.md")]
    )
    assert result.returncode != 0


def test_placeholder_only_anchor_does_not_wildcard_match(tmp_path):
    """Locks the MIN_ANCHOR_NON_SENTINEL_CHARS guard. A spec line whose
    anchor consists only of a placeholder (`<X>`) used to collapse the
    sentinel-fallback regex to bare `\\S+`, matching any nonblank token in
    any plan line and producing a spurious `is_substituted=True` against
    the first such line. With the guard the sentinel fallback is suppressed
    and Jaccard scoring (which has no anchor tokens to match against) finds
    no candidate, so `found` is False and the unmatched_reason is reported."""
    spec = tmp_path / "spec.md"
    plan = tmp_path / "plan.md"
    spec.write_text("`<X>`\n")
    plan.write_text("totally unrelated prose with no shared tokens.\n")
    result = run(["--spec-path", str(spec), "--plan-path", str(plan)])
    out = json.loads(result.stdout)
    p = out["spec_placeholders"][0]
    assert p["plan_correspondence"]["found"] is False
    assert p["plan_correspondence"]["unmatched_reason"] == "no_plan_line_above_threshold"
