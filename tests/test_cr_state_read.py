"""Tests for cr_state_read.py."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPERS = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers"
SCRIPT = HELPERS / "cr_state_read.py"
INIT = HELPERS / "cr_state_init.py"
WRITE = HELPERS / "cr_state_write.py"


def run(script, args, cwd, stdin=None):
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
    )


@pytest.fixture
def workspace(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "docs/specs").mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "tests/fixtures/artifacts/spec.md", tmp_path / "docs/specs/foo-design.md"
    )
    schema_dst = tmp_path / "plugin/skills/cr/_shared/schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "plugin/skills/cr/_shared/schema", schema_dst)
    return tmp_path


@pytest.fixture
def workspace_with_1a(workspace):
    artifact = workspace / "docs/specs/foo-design.md"
    run(
        INIT,
        ["--artifact-path", str(artifact), "--artifact-type", "spec", "--no-gitignore-prompt"],
        cwd=workspace,
        stdin="",
    )
    run(
        WRITE,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(REPO_ROOT / "tests/fixtures/state_write_inputs/round_1a_input.json"),
        ],
        cwd=workspace,
    )
    return workspace


def test_read_after_1a_returns_state_and_ok(workspace_with_1a):
    result = run(SCRIPT, ["--slug", "foo", "--artifact-type", "spec"], cwd=workspace_with_1a)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state"]["spec"]["current_stage"] == "round_1b_pending"
    assert payload["integrity"] == "OK"


def test_orphan_round_file_is_discarded(workspace_with_1a):
    # write an orphan round-2a.json (state hasn't completed it yet)
    spec_dir = workspace_with_1a / ".cross-agent-reviews/foo/spec"
    (spec_dir / "round-2a.json").write_text('{"stage": "2a", "junk": true}')
    result = run(SCRIPT, ["--slug", "foo", "--artifact-type", "spec"], cwd=workspace_with_1a)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["integrity"] in {"OK", "ORPHAN_DISCARDED"}
    # orphan file moved aside
    assert not (spec_dir / "round-2a.json").exists()
    discards = list(spec_dir.glob(".discard-*"))
    assert len(discards) == 1


def test_malformed_round_file_is_renamed_not_crashed(workspace_with_1a):
    """A malformed round file (invalid JSON) on disk for a stage that IS in
    `completed_rounds` must not crash `_read_round_files`. The original
    orphan-discard branch only fires for stages NOT in completed_rounds, so
    a malformed-but-completed file would otherwise propagate `JSONDecodeError`
    out of `_cmd_read`. The script must rename the malformed file aside with
    a `.discard-<ts>-malformed-round-<stage>.json` prefix and treat it as
    absent for downstream classification (where the pending-import logic
    then picks it up naturally)."""
    spec_dir = workspace_with_1a / ".cross-agent-reviews/foo/spec"
    state_path = workspace_with_1a / ".cross-agent-reviews/foo/state.json"
    # Mark 2a as completed in state so the file is NOT classified as orphan,
    # then drop malformed bytes into round-2a.json. Without the malformed-
    # handling, json.loads in _read_round_files crashes the whole read.
    state = json.loads(state_path.read_text())
    state["spec"]["completed_rounds"] = sorted({*state["spec"]["completed_rounds"], "2a"})
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    (spec_dir / "round-2a.json").write_text("not valid JSON{{{")
    result = run(SCRIPT, ["--slug", "foo", "--artifact-type", "spec"], cwd=workspace_with_1a)
    assert result.returncode == 0, result.stderr
    # Original malformed file moved aside.
    assert not (spec_dir / "round-2a.json").exists()
    malformed_discards = list(spec_dir.glob(".discard-*-malformed-round-2a.json"))
    assert len(malformed_discards) == 1
    # Operator-facing diagnostic on stderr names the path.
    assert "malformed" in result.stderr.lower()


def test_orphan_with_malformed_uses_distinct_prefix(workspace_with_1a):
    """Orphan files (stage NOT in completed_rounds, JSON parses) must keep
    using the existing `.discard-<ts>-round-<stage>.json` rename — only
    malformed files (JSON does not parse) get the `malformed-` infix. The
    distinct prefix lets an operator inspecting the directory tell the two
    recovery kinds apart."""
    spec_dir = workspace_with_1a / ".cross-agent-reviews/foo/spec"
    # Orphan: 2a stage is NOT in completed_rounds, but the file parses fine.
    (spec_dir / "round-2a.json").write_text('{"stage": "2a", "junk": true}')
    result = run(SCRIPT, ["--slug", "foo", "--artifact-type", "spec"], cwd=workspace_with_1a)
    assert result.returncode == 0
    # Orphan-style discard exists, malformed-style discard does NOT.
    orphan_discards = list(spec_dir.glob(".discard-*-round-2a.json"))
    malformed_discards = list(spec_dir.glob(".discard-*-malformed-round-2a.json"))
    assert len(orphan_discards) == 1
    assert len(malformed_discards) == 0


def test_malformed_and_orphan_coexist_in_one_run(workspace_with_1a):
    """A directory can contain BOTH a malformed completed-round file (e.g.
    round-2a.json with bad JSON, 2a in completed_rounds) AND an unrelated
    orphan round file (e.g. round-3a.json with valid JSON but 3a NOT in
    completed_rounds). One read pass must rename both — malformed with the
    `malformed-` infix, orphan with the plain `.discard-<ts>-round-` prefix
    — and exit 0."""
    spec_dir = workspace_with_1a / ".cross-agent-reviews/foo/spec"
    state_path = workspace_with_1a / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["completed_rounds"] = sorted({*state["spec"]["completed_rounds"], "2a"})
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    # Malformed completed-round file.
    (spec_dir / "round-2a.json").write_text("not valid JSON{{{")
    # Unrelated orphan (3a is NOT in completed_rounds).
    (spec_dir / "round-3a.json").write_text('{"stage": "3a", "junk": true}')
    result = run(SCRIPT, ["--slug", "foo", "--artifact-type", "spec"], cwd=workspace_with_1a)
    assert result.returncode == 0, result.stderr
    assert not (spec_dir / "round-2a.json").exists()
    assert not (spec_dir / "round-3a.json").exists()
    malformed_discards = list(spec_dir.glob(".discard-*-malformed-round-2a.json"))
    orphan_discards = list(spec_dir.glob(".discard-*-round-3a.json"))
    # Filter out any malformed-prefixed match from the orphan glob (the
    # malformed pattern is a superset of the orphan pattern textually).
    orphan_discards = [p for p in orphan_discards if "malformed" not in p.name]
    assert len(malformed_discards) == 1
    assert len(orphan_discards) == 1


def test_missing_referenced_round_signals_pending_import(workspace_with_1a):
    spec_dir = workspace_with_1a / ".cross-agent-reviews/foo/spec"
    (spec_dir / "round-1a.json").unlink()
    result = run(SCRIPT, ["--slug", "foo", "--artifact-type", "spec"], cwd=workspace_with_1a)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["pending_import"] is True
    assert payload["pending_stage"] == "1a"


def test_state_regression_halts(workspace_with_1a):
    state_path = workspace_with_1a / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["last_updated_at"] = "2000-01-01T00:00:00Z"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    result = run(SCRIPT, ["--slug", "foo", "--artifact-type", "spec"], cwd=workspace_with_1a)
    assert result.returncode == 3
    assert "STATE_INTEGRITY_ERROR" in result.stderr


def test_paste_bootstrap_from_state_json(workspace, fixtures_dir):
    payload = (fixtures_dir / "schema_positive/state_spec_only.json").read_text()
    result = run(SCRIPT, ["--paste", "--slug", "2026-05-07-issue-1"], cwd=workspace, stdin=payload)
    assert result.returncode == 0, result.stderr
    state = json.loads(
        (workspace / ".cross-agent-reviews/2026-05-07-issue-1/state.json").read_text()
    )
    assert state["slug"] == "2026-05-07-issue-1"


def test_paste_bootstrap_refuses_clobber(workspace_with_1a, fixtures_dir):
    payload = (fixtures_dir / "schema_positive/state_spec_only.json").read_text()
    result = run(SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=payload)
    assert result.returncode == 1
    assert "already" in result.stderr.lower() or "clobber" in result.stderr.lower()


def test_paste_bootstrap_rejects_both_blocks_missing_spec_anchor(workspace):
    """A pasted bootstrap with both spec and plan blocks must carry
    plan.spec_hash_at_start. The state.schema.json cannot conditionally
    require it; the script must reject it explicitly so spec-drift
    protection is not silently bypassed on the destination host."""
    state = {
        "schema_version": 1,
        "slug": "2026-05-07-issue-1",
        "spec": {
            "path": "docs/specs/foo-design.md",
            "content_hash": "sha256:" + "0" * 64,
            "current_stage": "ready_for_implementation",
            "completed_rounds": ["1a", "1b", "2a", "2b", "3a", "3b"],
            "started_at": "2026-05-07T10:00:00Z",
            "last_updated_at": "2026-05-07T10:30:00Z",
        },
        "plan": {
            "path": "docs/plans/foo-plan.md",
            "content_hash": "sha256:" + "1" * 64,
            "current_stage": "round_1a_pending",
            "completed_rounds": [],
            "started_at": "2026-05-07T11:00:00Z",
            "last_updated_at": "2026-05-07T11:00:00Z",
            # NOTE: deliberately omit spec_hash_at_start
        },
    }
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    result = run(SCRIPT, ["--paste", "--slug", "2026-05-07-issue-1"], cwd=workspace, stdin=payload)
    assert result.returncode == 1
    assert "spec_hash_at_start" in result.stderr


def _bootstrap_payload(stage: str, completed: list[str], block: str = "spec") -> str:
    """Build a minimal bootstrap state.json with the given block-under-test
    set to (`current_stage`, `completed_rounds`). Used by the
    impossible-transition invariant tests to vary one block at a time —
    we never set both blocks here so the both-block `spec_hash_at_start`
    invariant cannot fire and confuse the assertion."""
    state = {
        "schema_version": 1,
        "slug": "2026-05-07-issue-1",
        block: {
            "path": f"docs/{block}s/foo-{block}.md",
            "content_hash": "sha256:" + "0" * 64,
            "current_stage": stage,
            "completed_rounds": completed,
            "started_at": "2026-05-07T10:00:00Z",
            "last_updated_at": "2026-05-07T10:30:00Z",
        },
    }
    return json.dumps(state, indent=2, sort_keys=True) + "\n"


def test_bootstrap_paste_rejects_round_3a_pending_with_empty_completed(workspace):
    """A bootstrap paste with current_stage='round_3a_pending' is logically
    impossible: rounds 1a/1b/2a/2b must be done first. Schema validation
    cannot express this; the script-invariant layer must reject it before
    any downstream operation jumps to round 3a with no prior round files."""
    payload = _bootstrap_payload("round_3a_pending", [])
    result = run(SCRIPT, ["--paste", "--slug", "2026-05-07-issue-1"], cwd=workspace, stdin=payload)
    assert result.returncode == 1
    assert "state integrity" in result.stderr.lower() or "round_3a_pending" in result.stderr
    assert "spec" in result.stderr  # block name in diagnostic


def test_bootstrap_paste_rejects_round_2b_pending_with_partial_completed(workspace):
    """current_stage='round_2b_pending' with completed_rounds=['1a','1b','2a']
    looks consistent (the 2b stage IS what comes after 2a) but is still an
    illegal bootstrap — bootstrap is for a fresh pipeline (round_1a_pending,
    empty) or a terminal handoff (ready_for_implementation, all six). Anything
    in between must come from local writes, not a paste."""
    payload = _bootstrap_payload("round_2b_pending", ["1a", "1b", "2a"], block="plan")
    result = run(SCRIPT, ["--paste", "--slug", "2026-05-07-issue-1"], cwd=workspace, stdin=payload)
    assert result.returncode == 1
    assert "round_2b_pending" in result.stderr
    assert "plan" in result.stderr  # block name in diagnostic


def test_bootstrap_paste_accepts_fresh_pipeline_init(workspace):
    """A bootstrap with current_stage='round_1a_pending' and empty
    completed_rounds is the canonical fresh-pipeline init. Must succeed."""
    payload = _bootstrap_payload("round_1a_pending", [])
    result = run(SCRIPT, ["--paste", "--slug", "2026-05-07-issue-1"], cwd=workspace, stdin=payload)
    assert result.returncode == 0, result.stderr


def test_bootstrap_paste_accepts_terminal_handoff(workspace):
    """A bootstrap with current_stage='ready_for_implementation' and
    completed_rounds containing all six stages is the canonical terminal
    cross-host handoff (pipeline already ran on Host A; paste informs Host
    B that work is done). Must succeed."""
    payload = _bootstrap_payload("ready_for_implementation", ["1a", "1b", "2a", "2b", "3a", "3b"])
    result = run(SCRIPT, ["--paste", "--slug", "2026-05-07-issue-1"], cwd=workspace, stdin=payload)
    assert result.returncode == 0, result.stderr


def test_bootstrap_paste_rejects_terminal_with_partial_completed(workspace):
    """current_stage='ready_for_implementation' but completed_rounds=['1a']
    is impossible: terminal stage requires all six rounds done. Reject."""
    payload = _bootstrap_payload("ready_for_implementation", ["1a"])
    result = run(SCRIPT, ["--paste", "--slug", "2026-05-07-issue-1"], cwd=workspace, stdin=payload)
    assert result.returncode == 1
    assert "ready_for_implementation" in result.stderr


def test_bootstrap_paste_rejects_round_1a_pending_with_nonempty_completed(workspace):
    """current_stage='round_1a_pending' but completed_rounds=['1a'] is
    contradictory — round_1a_pending means 1a hasn't happened yet. Reject."""
    payload = _bootstrap_payload("round_1a_pending", ["1a"])
    result = run(SCRIPT, ["--paste", "--slug", "2026-05-07-issue-1"], cwd=workspace, stdin=payload)
    assert result.returncode == 1
    assert "round_1a_pending" in result.stderr


def test_paste_round_wrong_stage_rejected(workspace_with_1a, fixtures_dir):
    payload = (fixtures_dir / "schema_positive/round_3a_audit.json").read_text()
    result = run(SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=payload)
    assert result.returncode == 1
    assert "stage" in result.stderr.lower()


def test_paste_round_wrong_slug_rejected(workspace_with_1a, fixtures_dir):
    bad = json.loads((fixtures_dir / "schema_positive/round_1a_audit.json").read_text())
    # the existing slug in workspace_with_1a is "foo"; pretend the paste names another slug
    bad["slug"] = "different-slug"
    result = run(SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(bad))
    assert result.returncode == 1
    assert "slug" in result.stderr.lower()


def test_paste_settle_missing_adjudication_rejected(workspace_with_1a, fixtures_dir):
    """Settle paste must replay the same cross-round invariants
    `_build_settle_envelope` enforces locally. This case takes a 1b
    envelope whose paired 1a (already on disk via workspace_with_1a) has at
    least one finding, but the 1b adjudications array is empty — schema-
    valid yet locally impossible. Without `_settle_paste_invariants`
    running, the paste would silently advance state to round_2a_pending."""
    bad = json.loads((fixtures_dir / "schema_positive/round_1b_settle.json").read_text())
    bad["slug"] = "foo"
    bad["artifact_type"] = "spec"
    bad["artifact_path"] = "docs/specs/foo-design.md"
    bad["adjudications"] = []
    bad["adjudication_summary"] = {"accepted": 0, "rejected": 0}
    bad["accepted_findings"] = []
    bad["rejected_findings"] = []
    bad["changelog"] = []
    bad["self_review"] = []
    result = run(SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(bad))
    assert result.returncode == 1
    assert "missing an adjudication" in result.stderr or "missing" in result.stderr.lower()


def test_paste_settle_accepted_without_changelog_rejected(workspace_with_1a, fixtures_dir):
    """Schema-valid 1b paste that accepts a 1a finding but omits the
    matching changelog entry must be rejected at paste time, mirroring the
    `accepted finding(s) missing a changelog entry` check that
    `cr_state_write.py` enforces on local builds."""
    # Read prior 1a from the workspace to discover a real finding id.
    prior_1a = json.loads(
        (workspace_with_1a / ".cross-agent-reviews/foo/spec/round-1a.json").read_text()
    )
    real_id = next(f["id"] for agent in prior_1a["agents"] for f in agent["findings"])
    base_1b = json.loads((fixtures_dir / "schema_positive/round_1b_settle.json").read_text())
    base_1b["slug"] = "foo"
    base_1b["artifact_type"] = "spec"
    base_1b["artifact_path"] = "docs/specs/foo-design.md"
    # Cover every 1a finding with an adjudication; accept the first one but
    # deliberately omit its changelog + self_review entries.
    all_1a_ids = [f["id"] for agent in prior_1a["agents"] for f in agent["findings"]]
    base_1b["adjudications"] = [
        {
            "finding_id": fid,
            "verdict": "accept" if fid == real_id else "reject",
            "reasoning": "regression fixture",
        }
        for fid in all_1a_ids
    ]
    base_1b["adjudication_summary"] = {"accepted": 1, "rejected": len(all_1a_ids) - 1}
    base_1b["accepted_findings"] = [
        f for agent in prior_1a["agents"] for f in agent["findings"] if f["id"] == real_id
    ]
    base_1b["rejected_findings"] = []
    base_1b["changelog"] = []  # ← the missing-changelog invariant fires
    base_1b["self_review"] = []
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(base_1b)
    )
    assert result.returncode == 1
    assert "changelog" in result.stderr.lower()


def test_paste_settle_accepted_findings_diverges_from_adjudications_rejected(
    workspace_with_1a, fixtures_dir
):
    """Schema-valid 1b paste whose `accepted_findings` array does not match
    the set of `adjudications[verdict == accept]` must be rejected at paste
    time. `cr_state_write.py::_build_settle_envelope` synthesizes
    `accepted_findings` from the adjudications and the paired audit, so a
    locally-emitted envelope is consistent by construction; a hand-built
    paste could omit or stuff the field. Without this check, a downstream
    2a verifier reading `accepted_findings` would have nothing to verify."""
    prior_1a = json.loads(
        (workspace_with_1a / ".cross-agent-reviews/foo/spec/round-1a.json").read_text()
    )
    real_id = next(f["id"] for agent in prior_1a["agents"] for f in agent["findings"])
    all_1a_ids = [f["id"] for agent in prior_1a["agents"] for f in agent["findings"]]
    base_1b = json.loads((fixtures_dir / "schema_positive/round_1b_settle.json").read_text())
    base_1b["slug"] = "foo"
    base_1b["artifact_type"] = "spec"
    base_1b["artifact_path"] = "docs/specs/foo-design.md"
    base_1b["adjudications"] = [
        {
            "finding_id": fid,
            "verdict": "accept" if fid == real_id else "reject",
            "reasoning": "regression fixture",
        }
        for fid in all_1a_ids
    ]
    base_1b["adjudication_summary"] = {"accepted": 1, "rejected": len(all_1a_ids) - 1}
    # The adjudications accept `real_id`, but accepted_findings is empty — divergence.
    base_1b["accepted_findings"] = []
    base_1b["rejected_findings"] = []
    base_1b["changelog"] = [{"finding_id": real_id, "change_made": "edited"}]
    base_1b["self_review"] = [
        {
            "finding_id": real_id,
            "resolved": True,
            "over_specified": False,
            "introduces_contradiction": False,
            "notes": "",
        }
    ]
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(base_1b)
    )
    assert result.returncode == 1
    assert "accepted_findings" in result.stderr


def test_paste_settle_accepted_finding_severity_mutation_rejected(workspace_with_1a, fixtures_dir):
    """A pasted settle envelope's `accepted_findings` must match — by full
    object content, not just id — what the writer would derive from the
    paired audit. The paired 1a on disk has R1-1-001 at severity `blocker`;
    a paste that keeps the id but mutates the embedded severity to `nit`
    (now schema-valid for 1b) must still be rejected by the derived-content
    equality check. Schema validation alone cannot catch this once 1b/2b
    accept the full severity enum."""
    base_1b = json.loads((fixtures_dir / "schema_positive/round_1b_settle.json").read_text())
    base_1b["slug"] = "foo"
    base_1b["artifact_type"] = "spec"
    base_1b["artifact_path"] = "docs/specs/foo-design.md"
    base_1b["accepted_findings"][0]["severity"] = "nit"
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(base_1b)
    )
    assert result.returncode == 1
    assert "accepted_findings" in result.stderr


def test_paste_settle_rejected_finding_rejection_reason_mutation_rejected(
    workspace_with_1a, fixtures_dir
):
    """A pasted settle envelope's `rejected_findings` must match what the
    writer derives: each entry is the paired-audit finding plus a
    `rejection_reason` equal to the matching adjudication's `reasoning`. A
    paste that keeps the finding id but sets a `rejection_reason` diverging
    from its adjudication must be rejected — id-set equality cannot catch it."""
    prior_1a = json.loads(
        (workspace_with_1a / ".cross-agent-reviews/foo/spec/round-1a.json").read_text()
    )
    finding = next(f for agent in prior_1a["agents"] for f in agent["findings"])
    base_1b = json.loads((fixtures_dir / "schema_positive/round_1b_settle.json").read_text())
    base_1b["slug"] = "foo"
    base_1b["artifact_type"] = "spec"
    base_1b["artifact_path"] = "docs/specs/foo-design.md"
    base_1b["adjudications"] = [
        {"finding_id": finding["id"], "verdict": "reject", "reasoning": "Not a real problem."}
    ]
    base_1b["adjudication_summary"] = {"accepted": 0, "rejected": 1}
    base_1b["accepted_findings"] = []
    # rejection_reason deliberately differs from the adjudication's reasoning.
    base_1b["rejected_findings"] = [{**finding, "rejection_reason": "A different reason."}]
    base_1b["changelog"] = []
    base_1b["self_review"] = []
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(base_1b)
    )
    assert result.returncode == 1
    assert "rejected_findings" in result.stderr


def test_paste_settle_rejected_finding_copied_content_mutation_rejected(
    workspace_with_1a, fixtures_dir
):
    """The `rejected_findings` parity check must compare the *copied audit
    content* of each entry, not just its id and `rejection_reason`. Here the
    `rejection_reason` matches the adjudication's `reasoning` exactly, but a
    copied audit field (`severity`) is mutated away from the paired 1a on
    disk. A check that compared only ids + `rejection_reason` would miss this;
    the full parsed-object equality must reject it."""
    prior_1a = json.loads(
        (workspace_with_1a / ".cross-agent-reviews/foo/spec/round-1a.json").read_text()
    )
    finding = next(f for agent in prior_1a["agents"] for f in agent["findings"])
    base_1b = json.loads((fixtures_dir / "schema_positive/round_1b_settle.json").read_text())
    base_1b["slug"] = "foo"
    base_1b["artifact_type"] = "spec"
    base_1b["artifact_path"] = "docs/specs/foo-design.md"
    base_1b["adjudications"] = [
        {"finding_id": finding["id"], "verdict": "reject", "reasoning": "Not a real problem."}
    ]
    base_1b["adjudication_summary"] = {"accepted": 0, "rejected": 1}
    base_1b["accepted_findings"] = []
    # rejection_reason matches the adjudication's reasoning; the divergence is
    # in a copied audit field (`severity`), which the writer would inherit
    # verbatim from the paired 1a.
    base_1b["rejected_findings"] = [
        {**finding, "severity": "nit", "rejection_reason": "Not a real problem."}
    ]
    base_1b["changelog"] = []
    base_1b["self_review"] = []
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(base_1b)
    )
    assert result.returncode == 1
    assert "rejected_findings" in result.stderr


def _walk_workspace_to_2b_pending(workspace, fid="R1-1-001", status="not_resolved"):
    """Advance workspace state through 1a → 1b → 2a so a 2b paste can be
    exercised. Forges a paired 2a round file with the named verification's
    status flipped (defaults to `not_resolved`, the precondition for a
    legitimate 2b revisit). Returns the per-test artifact directory."""
    state_path = workspace / ".cross-agent-reviews/foo/state.json"
    spec_dir = workspace / ".cross-agent-reviews/foo/spec"
    # Use the existing 1a on disk to construct minimal 1b and 2a envelopes
    # that satisfy the paired-audit shape `_settle_paste_invariants` reads.
    audit_1a = json.loads((spec_dir / "round-1a.json").read_text())
    settle_1b = {
        "round": 1,
        "stage": "1b",
        "schema_version": 1,
        "slug": audit_1a["slug"],
        "artifact_type": audit_1a["artifact_type"],
        "artifact_path": audit_1a["artifact_path"],
        "emitted_at": audit_1a["emitted_at"],
        "slice_plan": audit_1a["slice_plan"],
        "adjudication_summary": {"accepted": 1, "rejected": 0},
        "adjudications": [
            {"finding_id": fid, "verdict": "accept", "reasoning": "regression fixture"}
        ],
        "accepted_findings": [
            f for agent in audit_1a["agents"] for f in agent["findings"] if f["id"] == fid
        ],
        "rejected_findings": [],
        "changelog": [{"finding_id": fid, "change_made": "edited"}],
        "self_review": [
            {
                "finding_id": fid,
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "",
            }
        ],
    }
    (spec_dir / "round-1b.json").write_text(json.dumps(settle_1b, indent=2, sort_keys=True) + "\n")
    audit_2a = json.loads(json.dumps(audit_1a))  # deep copy
    audit_2a.update({"round": 2, "stage": "2a"})
    for agent in audit_2a["agents"]:
        agent["status"] = "verified"
        agent["findings"] = []
        agent["round_1_verifications"] = []
    # Place the named verification on the agent that owns the finding id
    # (frozen-slice ownership: `R1-{agent_id}-...`).
    origin_agent_id = int(fid.split("-")[1])
    for agent in audit_2a["agents"]:
        if agent["agent_id"] == origin_agent_id:
            agent["round_1_verifications"] = [
                {
                    "round_1_finding_id": fid,
                    "status": status,
                    "evidence": "regression fixture",
                }
            ]
    (spec_dir / "round-2a.json").write_text(json.dumps(audit_2a, indent=2, sort_keys=True) + "\n")
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "round_2b_pending"
    state["spec"]["completed_rounds"] = ["1a", "1b", "2a"]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return spec_dir


def _build_2b_paste(spec_dir, *, changelog, self_review):
    """Build a schema-valid 2b settle envelope with caller-supplied changelog
    and self_review arrays. Adjudications and accepted_findings are empty
    because the paired 2a in `_walk_workspace_to_2b_pending` has no NEW
    findings — the only edits possible are revisit edits."""
    audit_2a = json.loads((spec_dir / "round-2a.json").read_text())
    return {
        "round": 2,
        "stage": "2b",
        "schema_version": 1,
        "slug": audit_2a["slug"],
        "artifact_type": audit_2a["artifact_type"],
        "artifact_path": audit_2a["artifact_path"],
        "emitted_at": "2026-05-08T11:00:00Z",
        "slice_plan": audit_2a["slice_plan"],
        "adjudication_summary": {"accepted": 0, "rejected": 0},
        "adjudications": [],
        "accepted_findings": [],
        "rejected_findings": [],
        "changelog": changelog,
        "self_review": self_review,
    }


def test_paste_2b_rejects_revisit_changelog_without_paired_self_review(workspace_with_1a):
    """M4 invariant 1, paste side: a pasted 2b envelope with a revisit
    changelog entry whose finding_id is in the paired 2a's
    `round_1_verifications` but has no matching self_review entry must be
    rejected. Mirrors the local-write check so cross-host parity holds."""
    spec_dir = _walk_workspace_to_2b_pending(workspace_with_1a)
    envelope = _build_2b_paste(
        spec_dir,
        changelog=[{"finding_id": "R1-1-001", "change_made": "edited"}],
        self_review=[],
    )
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(envelope)
    )
    assert result.returncode == 1
    assert "R1-1-001" in result.stderr
    assert "self_review" in result.stderr.lower() or "self review" in result.stderr.lower()


def test_paste_2b_rejects_revisit_self_review_without_paired_changelog(workspace_with_1a):
    """M4 invariant 1, paste side, reverse direction."""
    spec_dir = _walk_workspace_to_2b_pending(workspace_with_1a)
    envelope = _build_2b_paste(
        spec_dir,
        changelog=[],
        self_review=[
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "",
            }
        ],
    )
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(envelope)
    )
    assert result.returncode == 1
    assert "R1-1-001" in result.stderr
    assert "changelog" in result.stderr.lower()


def test_paste_2b_rejects_revisit_of_resolved_verification(workspace_with_1a):
    """M4 invariant 2, paste side: a pasted 2b envelope whose revisit
    changelog references a Round 1 finding whose paired 2a verification has
    status='resolved' must be rejected at paste time."""
    spec_dir = _walk_workspace_to_2b_pending(workspace_with_1a, status="resolved")
    envelope = _build_2b_paste(
        spec_dir,
        changelog=[{"finding_id": "R1-1-001", "change_made": "pointless revisit"}],
        self_review=[
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "",
            }
        ],
    )
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(envelope)
    )
    assert result.returncode == 1
    assert "R1-1-001" in result.stderr
    assert "resolved" in result.stderr.lower()


def test_paste_settle_3b_final_status_mismatch_rejected(workspace_with_1a, fixtures_dir):
    """A 3b paste whose `final_status` does not match the shape of
    `accepted_findings` must be rejected. `_build_settle_envelope` derives
    `final_status` (CORRECTED_AND_READY when accepted_findings is non-empty,
    else READY_FOR_IMPLEMENTATION); a hand-built paste could lie about
    terminal status while still parsing under the schema."""
    base_3b = json.loads((fixtures_dir / "schema_positive/round_3b_settle.json").read_text())
    base_3b["slug"] = "foo"
    base_3b["artifact_type"] = "spec"
    base_3b["artifact_path"] = "docs/specs/foo-design.md"
    # Empty accepted_findings should imply READY_FOR_IMPLEMENTATION; lying.
    base_3b["accepted_findings"] = []
    base_3b["adjudications"] = []
    base_3b["adjudication_summary"] = {"accepted": 0, "rejected": 0}
    base_3b["rejected_findings"] = []
    base_3b["changelog"] = []
    base_3b["self_review"] = []
    base_3b["final_status"] = "CORRECTED_AND_READY"
    # Walk workspace to round_3b_pending so the paste-stage check accepts a 3b.
    state_path = workspace_with_1a / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "round_3b_pending"
    state["spec"]["completed_rounds"] = ["1a", "1b", "2a", "2b", "3a"]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    # Forge the prerequisite paired 3a so `_settle_paste_invariants` finds it.
    spec_dir = workspace_with_1a / ".cross-agent-reviews/foo/spec"
    audit_3a = json.loads((spec_dir / "round-1a.json").read_text())
    audit_3a.update({"round": 3, "stage": "3a"})
    for agent in audit_3a["agents"]:
        agent["status"] = "ship_ready"
        agent["findings"] = []
        agent["round_1_verifications"] = []
    (spec_dir / "round-3a.json").write_text(json.dumps(audit_3a, indent=2, sort_keys=True) + "\n")
    # Forge minimal intermediate round files so the paste path can find them.
    for stage in ("1b", "2a", "2b"):
        if not (spec_dir / f"round-{stage}.json").exists():
            (spec_dir / f"round-{stage}.json").write_text('{"stage": "' + stage + '"}')
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(base_3b)
    )
    assert result.returncode == 1
    assert "final_status" in result.stderr


def test_paste_settle_refreshes_content_hash(workspace_with_1a, fixtures_dir):
    """Cross-host paste-import of a settle envelope (1b/2b/3b) MUST refresh
    `state.<artifact_type>.content_hash` to match the local artifact bytes,
    mirroring the local-write refresh in cr_state_write.py. The cross-host
    workflow ships the post-edit artifact alongside the envelope, so without
    this refresh, host B's state.json keeps the pre-edit hash and a later
    plan-init would anchor `plan.spec_hash_at_start` to the wrong bytes —
    the same false-drift symptom as the original local-write defect."""
    state_path = workspace_with_1a / ".cross-agent-reviews/foo/state.json"
    pre_hash = json.loads(state_path.read_text())["spec"]["content_hash"]
    artifact = workspace_with_1a / "docs/specs/foo-design.md"
    # Simulate host A's settle-edit shipped alongside the envelope.
    artifact.write_text(artifact.read_text() + "\n<!-- 1b correction -->\n")
    payload = json.loads((fixtures_dir / "schema_positive/round_1b_settle.json").read_text())
    payload["slug"] = "foo"
    payload["artifact_type"] = "spec"
    payload["artifact_path"] = "docs/specs/foo-design.md"
    result = run(
        SCRIPT, ["--paste", "--slug", "foo"], cwd=workspace_with_1a, stdin=json.dumps(payload)
    )
    assert result.returncode == 0, result.stderr
    state_after = json.loads(state_path.read_text())
    expected_hash = "sha256:" + __import__("hashlib").sha256(artifact.read_bytes()).hexdigest()
    assert state_after["spec"]["content_hash"] == expected_hash
    assert state_after["spec"]["content_hash"] != pre_hash


def test_check_spec_drift_clean(workspace_with_1a, tmp_path):
    # init a plan now (after marking spec terminal)
    state_path = workspace_with_1a / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "ready_for_implementation"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    plan = workspace_with_1a / "docs/plans"
    plan.mkdir(parents=True, exist_ok=True)
    plan_file = plan / "foo-plan.md"
    plan_file.write_text("# foo plan\n")
    run(
        INIT,
        ["--artifact-path", str(plan_file), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace_with_1a,
        stdin="",
    )
    result = run(SCRIPT, ["--slug", "foo", "--check-spec-drift"], cwd=workspace_with_1a)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["spec_drift"] is False


def test_resolve_drift_accept_refreshes_anchor(workspace_with_1a):
    """`--resolve-drift accept` is the scripted recovery the router invokes
    when the operator chooses `accept-drift` from §7.8 of the spec. It
    refreshes state.plan.spec_hash_at_start to the current spec hash and
    advances last_updated_at; subsequent --check-spec-drift returns clean."""
    state_path = workspace_with_1a / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "ready_for_implementation"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    plan_file = workspace_with_1a / "docs/plans/foo-plan.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text("# foo plan\n")
    run(
        INIT,
        ["--artifact-path", str(plan_file), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace_with_1a,
        stdin="",
    )
    spec_file = workspace_with_1a / "docs/specs/foo-design.md"
    spec_file.write_text(spec_file.read_text() + "\n## Mutation\n")
    # Drift should now be detected.
    drift = run(SCRIPT, ["--slug", "foo", "--check-spec-drift"], cwd=workspace_with_1a)
    assert drift.returncode == 2
    # Resolve via accept.
    resolve = run(SCRIPT, ["--slug", "foo", "--resolve-drift", "accept"], cwd=workspace_with_1a)
    assert resolve.returncode == 0, resolve.stderr
    # Drift now clean.
    after = run(SCRIPT, ["--slug", "foo", "--check-spec-drift"], cwd=workspace_with_1a)
    assert after.returncode == 0
    assert json.loads(after.stdout)["spec_drift"] is False


def test_resolve_drift_restart_archives_plan_block(workspace_with_1a):
    """`--resolve-drift restart` archives the in-flight plan/ subdirectory
    and removes the plan block from state.json so the operator can re-run
    `cr_state_init --artifact-type plan` against the now-current spec."""
    state_path = workspace_with_1a / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "ready_for_implementation"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    plan_file = workspace_with_1a / "docs/plans/foo-plan.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text("# foo plan\n")
    run(
        INIT,
        ["--artifact-path", str(plan_file), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace_with_1a,
        stdin="",
    )
    plan_dir = workspace_with_1a / ".cross-agent-reviews/foo/plan"
    plan_dir.mkdir(exist_ok=True)
    (plan_dir / "round-1a.json").write_text('{"sentinel": true}')
    spec_file = workspace_with_1a / "docs/specs/foo-design.md"
    spec_file.write_text(spec_file.read_text() + "\n## Mutation\n")
    resolve = run(SCRIPT, ["--slug", "foo", "--resolve-drift", "restart"], cwd=workspace_with_1a)
    assert resolve.returncode == 0, resolve.stderr
    state_after = json.loads(state_path.read_text())
    assert "plan" not in state_after
    archives = list((workspace_with_1a / ".cross-agent-reviews/foo").glob(".archive-*"))
    assert len(archives) == 1
    assert (archives[0] / "plan" / "round-1a.json").exists()


def test_check_spec_drift_detected(workspace_with_1a):
    state_path = workspace_with_1a / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "ready_for_implementation"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    plan_file = workspace_with_1a / "docs/plans/foo-plan.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text("# foo plan\n")
    run(
        INIT,
        ["--artifact-path", str(plan_file), "--artifact-type", "plan", "--no-gitignore-prompt"],
        cwd=workspace_with_1a,
        stdin="",
    )
    # mutate the spec on disk
    spec_file = workspace_with_1a / "docs/specs/foo-design.md"
    spec_file.write_text(spec_file.read_text() + "\n## Mutation\n")
    result = run(SCRIPT, ["--slug", "foo", "--check-spec-drift"], cwd=workspace_with_1a)
    assert result.returncode == 2
    assert "SPEC_DRIFT_DETECTED" in result.stderr
    payload = json.loads(result.stdout)
    assert payload["spec_drift"] is True
