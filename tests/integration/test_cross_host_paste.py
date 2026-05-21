"""Cross-host paste flow: bootstrap state.json + round paste round-trip."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPERS = REPO_ROOT / "plugin" / "skills" / "cr" / "_helpers"
READ = HELPERS / "cr_state_read.py"
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


def _make_workspace(root):
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    (root / "docs/specs").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "tests/fixtures/artifacts/spec.md", root / "docs/specs/foo-design.md")
    schema_dst = root / "plugin/skills/cr/_shared/schema"
    schema_dst.parent.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "plugin/skills/cr/_shared/schema", schema_dst)


def test_host_b_bootstrap_then_round_paste_back_to_host_a(tmp_path):
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    # Host A: init using a REPO-RELATIVE artifact path. The cross-host
    # paste-import contract enforces artifact_path identity across hosts;
    # using one canonical relative path here, in the Host B write call, and
    # in any subsequent paste keeps the test from depending on the script's
    # absolute->relative normalisation as a hidden assumption.
    init = run(
        INIT,
        [
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host_a,
        stdin="",
    )
    state_payload = init.stdout

    # Host B: bootstrap from pasted state.json
    boot = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=state_payload)
    assert boot.returncode == 0, boot.stderr

    # Host B: write round 1a (simulates the audit running on Host B)
    write_result = run(
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
        cwd=host_b,
    )
    assert write_result.returncode == 0, write_result.stderr
    round_1a_payload = write_result.stdout

    # Host A: paste-import round 1a from B
    paste = run(READ, ["--paste", "--slug", "foo"], cwd=host_a, stdin=round_1a_payload)
    assert paste.returncode == 0, paste.stderr
    state_a = json.loads((host_a / ".cross-agent-reviews/foo/state.json").read_text())
    assert "1a" in state_a["spec"]["completed_rounds"]


def test_wrong_stage_paste_rejected(tmp_path):
    host = tmp_path
    _make_workspace(host)
    init = run(
        INIT,
        [
            "--artifact-path",
            str(host / "docs/specs/foo-design.md"),
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host,
        stdin="",
    )
    assert init.returncode == 0
    # Pretend a 3a paste arrives instead of 1a
    fake_3a = json.loads(
        (REPO_ROOT / "tests/fixtures/schema_positive/round_3a_audit.json").read_text()
    )
    fake_3a["slug"] = "foo"
    fake_3a["artifact_path"] = "docs/specs/foo-design.md"
    result = run(READ, ["--paste", "--slug", "foo"], cwd=host, stdin=json.dumps(fake_3a))
    assert result.returncode == 1
    assert "stage" in result.stderr.lower()


def test_bootstrap_clobber_refused(tmp_path, fixtures_dir):
    host = tmp_path
    _make_workspace(host)
    run(
        INIT,
        [
            "--artifact-path",
            str(host / "docs/specs/foo-design.md"),
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host,
        stdin="",
    )
    payload = (REPO_ROOT / "tests/fixtures/schema_positive/state_spec_only.json").read_text()
    result = run(READ, ["--paste", "--slug", "foo"], cwd=host, stdin=payload)
    assert result.returncode == 1
    assert "clobber" in result.stderr.lower() or "already" in result.stderr.lower()


def test_wrong_artifact_path_paste_rejected(tmp_path):
    """Acceptance criterion #4 (§15) requires concrete-diagnostic rejection
    on identity mismatch — not just stage mismatch. Identity is `slug` +
    `artifact_type` + `artifact_path`. We mutate `artifact_path` and assert
    the paste is rejected with a path-specific diagnostic, distinct from
    the stage diagnostic exercised in `test_wrong_stage_paste_rejected`."""
    host = tmp_path
    _make_workspace(host)
    init = run(
        INIT,
        [
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host,
        stdin="",
    )
    assert init.returncode == 0
    # Build a Round 1a payload whose stage matches the next-expected stage
    # (so it would be accepted on stage grounds) but whose artifact_path
    # diverges from the canonical local one.
    bad = json.loads((REPO_ROOT / "tests/fixtures/schema_positive/round_1a_audit.json").read_text())
    bad["slug"] = "foo"
    bad["artifact_path"] = "docs/specs/different-design.md"
    result = run(READ, ["--paste", "--slug", "foo"], cwd=host, stdin=json.dumps(bad))
    assert result.returncode == 1
    # The diagnostic MUST mention artifact_path, not stage — proving the
    # identity layer caught it before any other layer.
    assert "artifact_path" in result.stderr.lower() or "path" in result.stderr.lower()
    assert "stage" not in result.stderr.lower()


def test_wrong_slug_paste_rejected(tmp_path):
    """Identity mismatch on `slug` (e.g., the operator pasted a payload
    intended for a different review). This surfaces before stage validation."""
    host = tmp_path
    _make_workspace(host)
    init = run(
        INIT,
        [
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host,
        stdin="",
    )
    assert init.returncode == 0
    bad = json.loads((REPO_ROOT / "tests/fixtures/schema_positive/round_1a_audit.json").read_text())
    bad["slug"] = "different-slug"
    bad["artifact_path"] = "docs/specs/foo-design.md"
    result = run(READ, ["--paste", "--slug", "foo"], cwd=host, stdin=json.dumps(bad))
    assert result.returncode == 1
    assert "slug" in result.stderr.lower()


def test_invariant_violating_2a_paste_rejected(tmp_path):
    """A 2a paste whose `slice_plan` diverges from the prior 1a slice plan
    is rejected — the same cross-round invariant `cr_state_write.py` enforces
    on local writes (frozen after Round 1a). Without this replay, a cross-host
    paste could import a schema-valid but locally-impossible round."""
    host = tmp_path
    _make_workspace(host)
    init = run(
        INIT,
        [
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host,
        stdin="",
    )
    assert init.returncode == 0
    # Walk forward to round 2a-pending: write 1a + 1b locally, then attempt
    # a 2a paste whose slice_plan has been mutated from the 1a baseline.
    write_1a = run(
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
        cwd=host,
    )
    assert write_1a.returncode == 0, write_1a.stderr
    write_1b = run(
        WRITE,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(REPO_ROOT / "tests/fixtures/state_write_inputs/round_1b_input.json"),
        ],
        cwd=host,
    )
    assert write_1b.returncode == 0, write_1b.stderr
    bad_2a = json.loads(
        (REPO_ROOT / "tests/fixtures/schema_positive/round_2a_audit.json").read_text()
    )
    bad_2a["slug"] = "foo"
    bad_2a["artifact_type"] = "spec"
    bad_2a["artifact_path"] = "docs/specs/foo-design.md"
    # Mutate one slice's `concern` semantically — the slice_plan stays
    # schema-valid (5 entries, all required fields present, valid agent_ids)
    # but diverges from the prior 1a baseline written above. This exercises
    # the cross-round frozen-slice invariant rather than schema validation,
    # which a wholesale-replacement slice_plan would short-circuit.
    bad_2a["slice_plan"][0]["concern"] = "Mutated concern (diverges from 1a baseline)"
    result = run(READ, ["--paste", "--slug", "foo"], cwd=host, stdin=json.dumps(bad_2a))
    assert result.returncode == 1
    assert "slice_plan" in result.stderr.lower()


def _walk_host_to_3a_pending(host):
    """Init a host and write rounds 1a..2b locally so it sits at
    round_3a_pending with all prior round files on disk."""
    init = run(
        INIT,
        [
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host,
        stdin="",
    )
    assert init.returncode == 0, init.stderr
    for stage_input in [
        "round_1a_input.json",
        "round_1b_input.json",
        "round_2a_input.json",
        "round_2b_input.json",
    ]:
        r = run(
            WRITE,
            [
                "--slug",
                "foo",
                "--artifact-type",
                "spec",
                "--artifact-path",
                "docs/specs/foo-design.md",
                "--input",
                str(REPO_ROOT / "tests/fixtures/state_write_inputs" / stage_input),
            ],
            cwd=host,
        )
        assert r.returncode == 0, f"{stage_input}: {r.stderr}"


def test_clean_3a_cross_host_handoff_terminates(tmp_path):
    """A clean 3a produced on Host A and pasted onto Host B terminates Host B
    at ready_for_implementation; the absent round-3b.json is never treated as
    a pending import."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)
    # Both hosts walk 1a..2b with identical fixtures, so their round-2a.json
    # slice plans match — required for the 3a paste's frozen-slice invariant.
    _walk_host_to_3a_pending(host_a)
    _walk_host_to_3a_pending(host_b)

    # Host A: write the clean 3a; capture the emitted envelope.
    write_3a = run(
        WRITE,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(REPO_ROOT / "tests/fixtures/state_write_inputs/round_3a_input.json"),
        ],
        cwd=host_a,
    )
    assert write_3a.returncode == 0, write_3a.stderr

    # Host B: paste-import the clean 3a envelope.
    paste = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=write_3a.stdout)
    assert paste.returncode == 0, paste.stderr
    state_b = json.loads((host_b / ".cross-agent-reviews/foo/state.json").read_text())
    assert state_b["spec"]["current_stage"] == "ready_for_implementation"
    assert state_b["spec"]["completed_rounds"] == ["1a", "1b", "2a", "2b", "3a"]
    assert not (host_b / ".cross-agent-reviews/foo/spec/round-3b.json").exists()

    # state-read on Host B must not flag the missing round-3b.json as pending.
    read = run(READ, ["--slug", "foo", "--artifact-type", "spec"], cwd=host_b)
    assert read.returncode == 0, read.stderr
    out = json.loads(read.stdout)
    assert out["pending_import"] is False
    assert out["integrity"] == "OK"


def _drive_host_to_3c_pending(host):
    """Init host and write rounds 1a..3b(accept) locally, ending at round_3c_pending.

    Returns a dict mapping stage name to the stdout emitted by cr_state_write.py
    for each stage (the canonical round envelopes), so callers can paste them
    to another host.
    """
    init = run(
        INIT,
        [
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host,
        stdin="",
    )
    assert init.returncode == 0, init.stderr
    stage_inputs = [
        ("1a", "round_1a_input.json"),
        ("1b", "round_1b_input.json"),
        ("2a", "round_2a_input.json"),
        ("2b", "round_2b_input.json"),
        ("3a", "round_3a_input_blocker.json"),
        ("3b", "round_3b_input_accept.json"),
    ]
    envelopes: dict[str, str] = {}
    for stage, input_file in stage_inputs:
        r = run(
            WRITE,
            [
                "--slug",
                "foo",
                "--artifact-type",
                "spec",
                "--artifact-path",
                "docs/specs/foo-design.md",
                "--input",
                str(REPO_ROOT / "tests/fixtures/state_write_inputs" / input_file),
            ],
            cwd=host,
        )
        assert r.returncode == 0, f"{input_file}: {r.stderr}"
        envelopes[stage] = r.stdout
    return envelopes


def test_cross_host_corrected_3b_then_3c(tmp_path):
    """Host A drives 1a→3b(accept), resulting in round_3c_pending.
    Host B bootstraps from Host A's state.json, pastes rounds 1a..3b,
    runs a passing 3c locally, and the resulting round-3c.json is pasted
    back to Host A — advancing both hosts to ready_for_implementation via_3c."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    # Host A: drive through 3b-accept and capture each round envelope.
    envelopes = _drive_host_to_3c_pending(host_a)

    state_a = json.loads((host_a / ".cross-agent-reviews/foo/state.json").read_text())
    assert state_a["spec"]["current_stage"] == "round_3c_pending"

    # Host B: bootstrap from Host A's state.json (paste via READ --paste --slug).
    state_payload = (host_a / ".cross-agent-reviews/foo/state.json").read_text()
    boot = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=state_payload)
    assert boot.returncode == 0, boot.stderr

    # Host B: paste-import rounds 1a..3b from Host A in pipeline order.
    for stage in ("1a", "1b", "2a", "2b", "3a", "3b"):
        paste = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=envelopes[stage])
        assert paste.returncode == 0, f"paste {stage}: {paste.stderr}"

    state_b = json.loads((host_b / ".cross-agent-reviews/foo/state.json").read_text())
    assert state_b["spec"]["current_stage"] == "round_3c_pending"

    # Host B: run a passing 3c locally.
    # The artifact bytes on Host B (spec.md) are identical to Host A's — no
    # modification occurred between 3b and 3c, so Host A's copy already
    # matches the verified_content_hash that 3c will record.
    write_3c = run(
        WRITE,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(REPO_ROOT / "tests/fixtures/state_write_inputs/round_3c_input_pass.json"),
        ],
        cwd=host_b,
    )
    assert write_3c.returncode == 0, write_3c.stderr

    state_b = json.loads((host_b / ".cross-agent-reviews/foo/state.json").read_text())
    assert state_b["spec"]["current_stage"] == "ready_for_implementation"

    # Host A: paste-import the passing round-3c.json from Host B.
    # Artifact-bytes parity: Host A holds the same spec.md bytes as Host B
    # (neither host modified the artifact after init), so the local hash on
    # Host A matches verified_content_hash in the pasted envelope.
    round_3c_payload = write_3c.stdout
    paste_3c = run(READ, ["--paste", "--slug", "foo"], cwd=host_a, stdin=round_3c_payload)
    assert paste_3c.returncode == 0, paste_3c.stderr

    state_a = json.loads((host_a / ".cross-agent-reviews/foo/state.json").read_text())
    assert state_a["spec"]["current_stage"] == "ready_for_implementation"
    assert set(state_a["spec"]["completed_rounds"]) == {"1a", "1b", "2a", "2b", "3a", "3b", "3c"}


def _walk_host_to_3b_pending(host):
    """Init a host and write rounds 1a..3a locally so it sits at
    round_3b_pending with all prior round files on disk. The 3a round
    carries a blocker (round_3a_input_blocker.json) so the pipeline routes
    to round_3b_pending rather than terminating at ready_for_implementation."""
    init = run(
        INIT,
        [
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host,
        stdin="",
    )
    assert init.returncode == 0, init.stderr
    for stage_input in [
        "round_1a_input.json",
        "round_1b_input.json",
        "round_2a_input.json",
        "round_2b_input.json",
        "round_3a_input_blocker.json",
    ]:
        r = run(
            WRITE,
            [
                "--slug",
                "foo",
                "--artifact-type",
                "spec",
                "--artifact-path",
                "docs/specs/foo-design.md",
                "--input",
                str(REPO_ROOT / "tests/fixtures/state_write_inputs" / stage_input),
            ],
            cwd=host,
        )
        assert r.returncode == 0, f"{stage_input}: {r.stderr}"


def test_forward_paste_accepted_3b_routes_to_round_3c_pending(tmp_path):
    """Forward import of an accepted (CORRECTED_PENDING_VERIFICATION) 3b:
    Host A drives 1a→3b-accept; Host B walks 1a..3a locally and sits at
    round_3b_pending. Pasting Host A's accepted round-3b.json must route
    Host B to round_3c_pending — NOT ready_for_implementation, which would
    be an immediately-invalid verification_skipped integrity state.

    This exercises the `pending is None` forward path of `_cmd_paste`,
    which must mirror the conditional 3b routing in `cr_state_write.py`."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    # Host B: walk 1a..3a locally so it genuinely sits at round_3b_pending
    # with all prior round files on disk (forward path, not backfill).
    _walk_host_to_3b_pending(host_b)

    # Host A: drive 1a→3b-accept and capture the round envelopes. Done after
    # Host B's walk so Host A's 3b `emitted_at` is no earlier than Host B's
    # local round files — keeping the pasted state's last_updated_at >= every
    # round's emitted_at (a state-integrity invariant checked on read).
    envelopes = _drive_host_to_3c_pending(host_a)
    state_b = json.loads((host_b / ".cross-agent-reviews/foo/state.json").read_text())
    assert state_b["spec"]["current_stage"] == "round_3b_pending"

    # Host B: paste-import Host A's accepted round-3b.json.
    paste = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=envelopes["3b"])
    assert paste.returncode == 0, paste.stderr

    state_b = json.loads((host_b / ".cross-agent-reviews/foo/state.json").read_text())
    assert state_b["spec"]["current_stage"] == "round_3c_pending"
    assert "3b" in state_b["spec"]["completed_rounds"]

    # A subsequent read must NOT report verification_skipped — the state is
    # a valid pre-3c handoff, not a broken via_3b terminal.
    read = run(READ, ["--slug", "foo", "--artifact-type", "spec"], cwd=host_b)
    assert read.returncode == 0, read.stderr
    out = json.loads(read.stdout)
    assert out["integrity"] == "OK"
    assert "verification" not in read.stderr.lower()


def test_backfill_via_3b_terminal_rejects_cpv_3b_paste(tmp_path):
    """Backfill parity guard: a host bootstrapped with a via_3b terminal
    (ready_for_implementation + completed rounds 1a..3b) asserts 3b was
    clean (READY_FOR_IMPLEMENTATION). Pasting a CORRECTED_PENDING_VERIFICATION
    round-3b.json into that terminal contradicts the bootstrapped shape — a
    CPV 3b implies a via_3c terminal, not via_3b. The paste must FAIL with a
    non-zero exit and leave no invalid state behind."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    # Host A: drive 1a→3b-accept to obtain a genuine accepted (CPV) 3b envelope.
    envelopes = _drive_host_to_3c_pending(host_a)

    # Host B: walk 1a..3a locally so the real prior round files are on disk
    # (the 3b paste replays cross-round invariants against round-3a.json, so
    # genuine round files are required — stubs would crash the invariant
    # replay before the parity guard is reached).
    _walk_host_to_3b_pending(host_b)
    # Hand-edit Host B's state into a via_3b terminal: ready_for_implementation
    # with completed rounds 1a..3b, but round-3b.json absent on disk so 3b is
    # the earliest completed-but-missing stage (the pending-import target).
    state_path = host_b / ".cross-agent-reviews/foo/state.json"
    state = json.loads(state_path.read_text())
    state["spec"]["current_stage"] = "ready_for_implementation"
    state["spec"]["completed_rounds"] = ["1a", "1b", "2a", "2b", "3a", "3b"]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    spec_dir = host_b / ".cross-agent-reviews/foo/spec"

    # Paste Host A's accepted (CPV) round-3b.json into the via_3b terminal.
    paste = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=envelopes["3b"])
    assert paste.returncode != 0, paste.stdout
    assert "via_3b" in paste.stderr or "via_3c" in paste.stderr
    # The contradicting round file must not be written.
    assert not (spec_dir / "round-3b.json").exists()


def test_cross_host_via_3b_with_cpv_is_integrity_error(tmp_path):
    """A host bootstrapped with a via_3b terminal whose round-3b.json carries
    CORRECTED_PENDING_VERIFICATION (3b accepted a blocker but 3c never ran)
    is reported as a STATE_INTEGRITY_ERROR verification_skipped."""
    host = tmp_path
    _make_workspace(host)

    # Build a via_3b-terminal state.json (ready_for_implementation + 1a..3b)
    # directly — we do not use the normal pipeline because we want to hand-craft
    # the CORRECTED_PENDING_VERIFICATION condition without driving a full review.
    slug_dir = host / ".cross-agent-reviews/foo"
    spec_dir = slug_dir / "spec"
    spec_dir.mkdir(parents=True)
    completed = ["1a", "1b", "2a", "2b", "3a", "3b"]
    state = {
        "schema_version": 1,
        "slug": "foo",
        "spec": {
            "path": "docs/specs/foo-design.md",
            "content_hash": "sha256:" + "0" * 64,
            "current_stage": "ready_for_implementation",
            "completed_rounds": completed,
            "started_at": "2026-05-16T09:00:00Z",
            "last_updated_at": "2026-05-16T10:00:00Z",
        },
    }
    (slug_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    # Write stub round files for 1a..2b and 3a; write round-3b.json carrying
    # CORRECTED_PENDING_VERIFICATION (accepted_findings non-empty).
    for stage in ("1a", "1b", "2a", "2b", "3a"):
        (spec_dir / f"round-{stage}.json").write_text(
            json.dumps({"stage": stage, "emitted_at": "2026-05-16T10:00:00Z"}) + "\n"
        )
    r3b = json.loads(
        (REPO_ROOT / "tests/fixtures/schema_positive/round_3b_settle_corrected.json").read_text()
    )
    r3b["emitted_at"] = "2026-05-16T10:00:00Z"
    (spec_dir / "round-3b.json").write_text(json.dumps(r3b, indent=2, sort_keys=True) + "\n")

    result = run(READ, ["--slug", "foo", "--artifact-type", "spec"], cwd=host)
    assert result.returncode == 3
    assert "final verification (3c) did not run" in result.stderr


# ---------------------------------------------------------------------------
# Task 12 — fast/patch lineage cross-host parity (issue #22, T31 / T32)
#
# These two tests pin the cross-host contract for the impact-routing pipeline:
# round-1b.json must be byte-identical after paste-import, and the route
# decision derived from prior rounds must be deterministic across hosts.
# Together they prove the writer / paste pipeline is host-neutral for the
# fast/patch profile that drives the new finding_lineage carry-forward.
# ---------------------------------------------------------------------------


def _init_fast_patch(host):
    """Init host with mode=fast, review_profile=patch."""
    return run(
        INIT,
        [
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
            "--mode",
            "fast",
            "--review-profile",
            "patch",
        ],
        cwd=host,
        stdin="",
    )


def _write_1a_fast_patch(host):
    """Write a 1a audit with one R1-1-001 finding on agent 1; suitable for
    fast/patch since it is not clean (no auto-settle). Returns the writer
    result so callers can inspect stdout / disk."""
    payload = {
        "stage": "1a",
        "slice_plan": [
            {
                "agent_id": 1,
                "concern": "Data model & schemas",
                "slice_definition": "§3-§5",
                "is_fixed": False,
            },
            {
                "agent_id": 2,
                "concern": "Error handling & edge cases",
                "slice_definition": "§6",
                "is_fixed": False,
            },
            {
                "agent_id": 3,
                "concern": "Acceptance criteria & testability",
                "slice_definition": "§7-§8",
                "is_fixed": False,
            },
            {
                "agent_id": 4,
                "concern": "Cross-section consistency",
                "slice_definition": "all",
                "is_fixed": False,
            },
            {
                "agent_id": 5,
                "concern": "Global coherence",
                "slice_definition": "all",
                "is_fixed": False,
            },
        ],
        "agents": [
            {
                "agent_id": 1,
                "concern": "Data model & schemas",
                "slice_definition": "§3-§5",
                "status": "findings_found",
                "findings": [
                    {
                        "location": "§3.2 line 47",
                        "severity": "blocker",
                        "finding": "Field foo is undefined.",
                        "why_it_matters": "Implementer cannot decide its type.",
                        "suggested_direction": "Define foo in §3.2.",
                    }
                ],
            },
            {
                "agent_id": 2,
                "concern": "Error handling & edge cases",
                "slice_definition": "§6",
                "status": "clean",
                "findings": [],
            },
            {
                "agent_id": 3,
                "concern": "Acceptance criteria & testability",
                "slice_definition": "§7-§8",
                "status": "clean",
                "findings": [],
            },
            {
                "agent_id": 4,
                "concern": "Cross-section consistency",
                "slice_definition": "all",
                "status": "clean",
                "findings": [],
            },
            {
                "agent_id": 5,
                "concern": "Global coherence",
                "slice_definition": "all",
                "status": "clean",
                "findings": [],
            },
        ],
    }
    input_path = host / "round_1a_lineage_input.json"
    input_path.write_text(json.dumps(payload))
    return run(
        WRITE,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(input_path),
        ],
        cwd=host,
    )


def _write_1b_fast_patch_accept(host):
    """Write a 1b that accepts R1-1-001 with complete lineage author fields
    (fix_criterion + verification_target + additional_affected_slices=[3])."""
    payload = {
        "stage": "1b",
        "adjudications": [
            {
                "finding_id": "R1-1-001",
                "verdict": "accept",
                "reasoning": "fix",
                "fix_criterion": "Define foo with a concrete type in §3.2.",
                "verification_target": "§3.2 declares foo: string.",
            }
        ],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R1-1-001",
                "change_made": "Defined foo as a string in §3.2.",
                "additional_affected_slices": [3],
            }
        ],
        "self_review": [
            {
                "finding_id": "R1-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "ok",
            }
        ],
    }
    input_path = host / "round_1b_lineage_input.json"
    input_path.write_text(json.dumps(payload))
    return run(
        WRITE,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(input_path),
        ],
        cwd=host,
    )


def test_paste_import_preserves_finding_lineage_byte_for_byte(tmp_path):
    """T31: drive a fast/patch pipeline through 1a→1b on host A; capture the
    canonical round-1b.json bytes. Host B is freshly init'd with the same
    mode/profile (the supported pre-1a bootstrap shape — paste-import does
    not accept a mid-pipeline bootstrap state). Host B paste-imports each
    round envelope (1a then 1b) and the resulting round-1b.json must be
    byte-identical to host A's. This pins the host-neutral canonical encoding
    that the finding_lineage carry-forward chain depends on."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    # Host A: init fast/patch, drive 1a → 1b.
    init_a = _init_fast_patch(host_a)
    assert init_a.returncode == 0, init_a.stderr
    r1a = _write_1a_fast_patch(host_a)
    assert r1a.returncode == 0, r1a.stderr
    r1b = _write_1b_fast_patch_accept(host_a)
    assert r1b.returncode == 0, r1b.stderr

    # Capture canonical bytes from host A's disk.
    round_1a_path_a = host_a / ".cross-agent-reviews/foo/spec/round-1a.json"
    round_1b_path_a = host_a / ".cross-agent-reviews/foo/spec/round-1b.json"
    round_1a_bytes_a = round_1a_path_a.read_bytes()
    round_1b_bytes_a = round_1b_path_a.read_bytes()
    # Sanity: the 1b envelope carries a finding_lineage row for R1-1-001
    # (fast/patch + complete author fields = lineage is emitted).
    settled_a = json.loads(round_1b_bytes_a)
    assert settled_a.get("finding_lineage"), "host A 1b must emit finding_lineage"

    # Host B: init fast/patch locally (matching mode/profile is required so
    # the paste-imported round envelopes' lineage gate aligns with the local
    # state block; a thorough init would fail invariant replay).
    init_b = _init_fast_patch(host_b)
    assert init_b.returncode == 0, init_b.stderr

    # Host B: paste-import 1a then 1b from host A's canonical disk bytes.
    paste_1a = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=round_1a_bytes_a.decode())
    assert paste_1a.returncode == 0, paste_1a.stderr
    paste_1b = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=round_1b_bytes_a.decode())
    assert paste_1b.returncode == 0, paste_1b.stderr

    # Byte-parity assertion: the lineage carry-forward chain depends on
    # round-1b.json being bit-identical across hosts. If canonical encoding
    # drifts (sort_keys, separators, trailing newline) the chain breaks
    # silently. Pin it here.
    round_1b_bytes_b = (host_b / ".cross-agent-reviews/foo/spec/round-1b.json").read_bytes()
    assert round_1b_bytes_b == round_1b_bytes_a


def _write_2a_narrow_135(host):
    """Write a narrow 2a covering {1,3,5} that verifies R1-1-001 as resolved.
    fast/patch + accepted R1-1-001 with additional_affected_slices=[3] yields
    a narrow route over slices {1, 3, 5} (origin 1 + impact 3 + global-coh 5).
    """
    concerns = {
        1: ("Data model & schemas", "§3-§5"),
        3: ("Acceptance criteria & testability", "§7-§8"),
        5: ("Global coherence", "all"),
    }
    agents = []
    for aid in (1, 3, 5):
        concern, slice_def = concerns[aid]
        verifications = (
            [
                {
                    "round_1_finding_id": "R1-1-001",
                    "status": "resolved",
                    "evidence": "§3.2 now defines foo: string.",
                }
            ]
            if aid == 1
            else []
        )
        agents.append(
            {
                "agent_id": aid,
                "concern": concern,
                "slice_definition": slice_def,
                "status": "verified",
                "findings": [],
                "round_1_verifications": verifications,
            }
        )
    input_path = host / "round_2a_narrow_input.json"
    input_path.write_text(json.dumps({"stage": "2a", "agents": agents}))
    return run(
        WRITE,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--input",
            str(input_path),
        ],
        cwd=host,
    )


def test_narrow_2a_envelope_paste_imports_under_route_decision(tmp_path):
    """T33: narrow 2a written on host A must paste-import on host B. The
    writer accepts only `decision.selected_slices` for a narrow route, so
    paste-import must replay the same route decision instead of comparing
    against the full slice_plan. Without route-awareness, every narrow audit
    envelope is rejected cross-host and the impact-routing feature is
    effectively single-host."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    # Host A: init + drive 1a → 1b → narrow 2a locally.
    assert _init_fast_patch(host_a).returncode == 0
    assert _write_1a_fast_patch(host_a).returncode == 0
    assert _write_1b_fast_patch_accept(host_a).returncode == 0
    r2a_a = _write_2a_narrow_135(host_a)
    assert r2a_a.returncode == 0, r2a_a.stderr
    round_2a_path_a = host_a / ".cross-agent-reviews/foo/spec/round-2a.json"
    settled_2a = json.loads(round_2a_path_a.read_text())
    actual_agents = sorted(a["agent_id"] for a in settled_2a["agents"])
    assert actual_agents == [1, 3, 5], (
        f"sanity: host A 2a must be narrow [1,3,5]; got {actual_agents}"
    )

    # Host B: init fast/patch, paste 1a + 1b so the route decision can be
    # re-derived from on-disk prior rounds.
    assert _init_fast_patch(host_b).returncode == 0
    for stage in ("1a", "1b"):
        env_bytes = (host_a / f".cross-agent-reviews/foo/spec/round-{stage}.json").read_bytes()
        paste = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=env_bytes.decode())
        assert paste.returncode == 0, f"paste {stage}: {paste.stderr}"

    # Now paste host A's narrow 2a. This must succeed: the writer accepted
    # it locally; cross-host paste must replay the same route decision.
    paste_2a = run(
        READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=round_2a_path_a.read_bytes().decode()
    )
    assert paste_2a.returncode == 0, paste_2a.stderr
    round_2a_b = (host_b / ".cross-agent-reviews/foo/spec/round-2a.json").read_bytes()
    assert round_2a_b == round_2a_path_a.read_bytes(), "narrow 2a must round-trip byte-identical"


def test_paste_rejects_1b_with_tampered_lineage_affected_slices(tmp_path):
    """T34: a fast/patch 1b paste whose finding_lineage row shrinks
    affected_slices below what the writer would have derived from the
    same adjudications + changelog must be rejected. Without this gate,
    a hand-edited or maliciously crafted 1b paste can silently narrow
    Round 1 evidence on the receiving host and let decide_3a skip a slice
    the original author edited."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    assert _init_fast_patch(host_a).returncode == 0
    assert _write_1a_fast_patch(host_a).returncode == 0
    assert _write_1b_fast_patch_accept(host_a).returncode == 0

    round_1a_bytes = (host_a / ".cross-agent-reviews/foo/spec/round-1a.json").read_bytes()
    settled_1b = json.loads((host_a / ".cross-agent-reviews/foo/spec/round-1b.json").read_bytes())
    # Sanity: writer emitted [1, 3] for R1-1-001 (origin 1 + additional 3).
    assert settled_1b["finding_lineage"][0]["affected_slices"] == [1, 3]
    # Tamper: shrink to [1]. Schema still validates (non-empty array of ints).
    settled_1b["finding_lineage"][0]["affected_slices"] = [1]
    tampered_1b = json.dumps(settled_1b)

    assert _init_fast_patch(host_b).returncode == 0
    paste_1a = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=round_1a_bytes.decode())
    assert paste_1a.returncode == 0, paste_1a.stderr

    paste_1b = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=tampered_1b)
    assert paste_1b.returncode != 0
    assert "lineage" in paste_1b.stderr.lower()


def test_paste_rejects_1b_with_missing_lineage_row_for_accepted_finding(tmp_path):
    """T35: a fast/patch 1b paste whose finding_lineage omits an accepted
    finding (with complete adjudication + changelog) must be rejected. The
    writer would emit a row; a paste that drops it produces lineage drift
    that decide_3a downstream cannot detect."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    assert _init_fast_patch(host_a).returncode == 0
    assert _write_1a_fast_patch(host_a).returncode == 0
    assert _write_1b_fast_patch_accept(host_a).returncode == 0

    round_1a_bytes = (host_a / ".cross-agent-reviews/foo/spec/round-1a.json").read_bytes()
    settled_1b = json.loads((host_a / ".cross-agent-reviews/foo/spec/round-1b.json").read_bytes())
    # Drop the lineage row entirely. Adjudications + changelog still
    # accept R1-1-001 with complete author fields.
    settled_1b["finding_lineage"] = []
    tampered_1b = json.dumps(settled_1b)

    assert _init_fast_patch(host_b).returncode == 0
    paste_1a = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=round_1a_bytes.decode())
    assert paste_1a.returncode == 0, paste_1a.stderr

    paste_1b = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=tampered_1b)
    assert paste_1b.returncode != 0
    assert "lineage" in paste_1b.stderr.lower()


def test_route_decision_identical_across_hosts(tmp_path):
    """T32: same fast/patch state on both hosts; running
    `cr_state_read.py --route-decision --stage 2a` on each emits byte-identical
    stdout. Pins host-neutrality of the route-decision derivation. Host B is
    bootstrapped via fresh init (matching mode/profile) and paste-import of
    every prior round envelope from host A."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    # Host A: init + 1a + 1b locally.
    assert _init_fast_patch(host_a).returncode == 0
    assert _write_1a_fast_patch(host_a).returncode == 0
    assert _write_1b_fast_patch_accept(host_a).returncode == 0

    # Host B: fresh init with matching mode/profile, then paste each round
    # envelope so both hosts hold identical prior-round files on disk.
    assert _init_fast_patch(host_b).returncode == 0
    for stage in ("1a", "1b"):
        env_bytes = (host_a / f".cross-agent-reviews/foo/spec/round-{stage}.json").read_bytes()
        paste = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=env_bytes.decode())
        assert paste.returncode == 0, f"paste {stage}: {paste.stderr}"

    # Compare stdout from --route-decision on both hosts.
    args = ["--slug", "foo", "--artifact-type", "spec", "--route-decision", "--stage", "2a"]
    out_a = run(READ, args, cwd=host_a)
    out_b = run(READ, args, cwd=host_b)
    assert out_a.returncode == 0, out_a.stderr
    assert out_b.returncode == 0, out_b.stderr
    assert out_a.stdout == out_b.stdout


def _init_legacy(host):
    """Init host with no --mode and no --review-profile (legacy/thorough).
    Local writer in this shape would NEVER emit finding_lineage."""
    return run(
        INIT,
        [
            "--artifact-path",
            "docs/specs/foo-design.md",
            "--artifact-type",
            "spec",
            "--no-gitignore-prompt",
        ],
        cwd=host,
        stdin="",
    )


def test_dispatch_bundle_emits_per_slice_payload(tmp_path):
    """`--dispatch-bundle` produces the narrow-routing payload described in
    `_shared/dispatch-template.md` (§Lineage-bundle payload). For the origin
    slice it lists the row under `verifications_for_this_slice`; for an
    impacted slice it lists the same row under `impacts_for_this_slice`;
    for the global-coherence slice it additionally emits `global_summary`."""
    host = tmp_path / "A"
    host.mkdir()
    _make_workspace(host)
    assert _init_fast_patch(host).returncode == 0
    assert _write_1a_fast_patch(host).returncode == 0
    assert _write_1b_fast_patch_accept(host).returncode == 0

    base = ["--slug", "foo", "--artifact-type", "spec", "--dispatch-bundle", "--stage", "2a"]
    out1 = run(READ, [*base, "--agent-id", "1"], cwd=host)
    out3 = run(READ, [*base, "--agent-id", "3"], cwd=host)
    out5 = run(READ, [*base, "--agent-id", "5"], cwd=host)
    assert out1.returncode == 0, out1.stderr
    assert out3.returncode == 0, out3.stderr
    assert out5.returncode == 0, out5.stderr

    bundle1 = json.loads(out1.stdout)
    bundle3 = json.loads(out3.stdout)
    bundle5 = json.loads(out5.stdout)

    assert len(bundle1["verifications_for_this_slice"]) == 1
    assert bundle1["verifications_for_this_slice"][0]["original_finding_id"] == "R1-1-001"
    assert bundle1["impacts_for_this_slice"] == []
    assert "global_summary" not in bundle1

    assert bundle3["verifications_for_this_slice"] == []
    assert len(bundle3["impacts_for_this_slice"]) == 1
    assert bundle3["impacts_for_this_slice"][0]["original_finding_id"] == "R1-1-001"
    assert "global_summary" not in bundle3

    assert "global_summary" in bundle5
    # accepted_findings_count must match edit_locations_compact 1:1 (one entry
    # per lineage row in the bundle). 2a stage: lineage has one row, accepted
    # has one finding, so count == 1.
    assert bundle5["global_summary"]["accepted_findings_count"] == 1
    assert len(bundle5["global_summary"]["edit_locations_compact"]) == 1
    assert bundle5["global_summary"]["all_affected_slices"] == [1, 3]


def test_dispatch_bundle_stage_3a_summary_count_matches_edit_locations(tmp_path):
    """3a bundle's global_summary.accepted_findings_count must align with
    edit_locations_compact 1:1 — both should reflect the full lineage
    (carry-forward 1b rows PLUS fresh 2a rows), not just settle.accepted.
    Synthesise a 2b file with one carry-forward + one fresh row and confirm
    the helper reports count == 2 (= len(edit_locations_compact))."""
    host = tmp_path / "A"
    host.mkdir()
    _make_workspace(host)
    assert _init_fast_patch(host).returncode == 0
    assert _write_1a_fast_patch(host).returncode == 0
    assert _write_1b_fast_patch_accept(host).returncode == 0

    # Direct-write a synthetic round-2a.json + round-2b.json on disk. The
    # dispatch-bundle helper only reads round-1a.json and the settle file
    # (round-2b for stage 3a), so we bypass the writer here to construct
    # a minimal mixed-lineage scenario without driving 2a end-to-end.
    artifact_dir = host / ".cross-agent-reviews/foo/spec"
    settled_1b = json.loads((artifact_dir / "round-1b.json").read_bytes())
    round_2a = {
        "round": 2,
        "stage": "2a",
        "schema_version": 1,
        "slug": "foo",
        "artifact_type": "spec",
        "artifact_path": "docs/specs/foo-design.md",
        "emitted_at": "2026-05-20T00:00:00Z",
        "slice_plan": settled_1b["slice_plan"],
        "agents": [
            {
                "agent_id": 1,
                "concern": "Data model & schemas",
                "slice_definition": "§3-§5",
                "status": "issues_found",
                "findings": [
                    {
                        "location": "§3.3 line 60",
                        "severity": "gap",
                        "finding": "Missing schema for bar.",
                        "why_it_matters": "Implementer cannot type bar.",
                        "suggested_direction": "Define bar in §3.3.",
                    }
                ],
                "round_1_verifications": [
                    {"round_1_finding_id": "R1-1-001", "status": "resolved", "evidence": "ok"}
                ],
            },
            *[
                {
                    "agent_id": i,
                    "concern": settled_1b["slice_plan"][i - 1]["concern"],
                    "slice_definition": settled_1b["slice_plan"][i - 1]["slice_definition"],
                    "status": "verified",
                    "findings": [],
                    "round_1_verifications": [],
                }
                for i in (2, 3, 4, 5)
            ],
        ],
    }
    (artifact_dir / "round-2a.json").write_text(json.dumps(round_2a))

    carry_forward = {
        **settled_1b["finding_lineage"][0],
        "lineage_id": "L-2b-R1-1-001",
        "prior_lineage_id": "L-1b-R1-1-001",
        "latest_verification": {"status": "resolved", "evidence": "ok"},
    }
    fresh_2a = {
        "lineage_id": "L-2b-R2-1-001",
        "original_finding_id": "R2-1-001",
        "originating_stage": "2a",
        "originating_agent_id": 1,
        "originating_slice": "Data model & schemas",
        "affected_location": "§3.3 line 60",
        "affected_slices": [1],
        "fix_criterion": "Define bar with a concrete type.",
        "verification_target": "§3.3 declares bar.",
        "prior_lineage_id": None,
        "latest_verification": None,
    }
    round_2b = {
        "round": 2,
        "stage": "2b",
        "schema_version": 1,
        "slug": "foo",
        "artifact_type": "spec",
        "artifact_path": "docs/specs/foo-design.md",
        "emitted_at": "2026-05-20T00:00:01Z",
        "slice_plan": settled_1b["slice_plan"],
        "adjudications": [
            {
                "finding_id": "R2-1-001",
                "verdict": "accept",
                "reasoning": "fix",
                "fix_criterion": "Define bar with a concrete type.",
                "verification_target": "§3.3 declares bar.",
            }
        ],
        "accepted_findings": [
            {
                "id": "R2-1-001",
                "location": "§3.3 line 60",
                "severity": "gap",
                "finding": "Missing schema for bar.",
                "why_it_matters": "Implementer cannot type bar.",
                "suggested_direction": "Define bar in §3.3.",
            }
        ],
        "rejected_findings": [],
        "changelog": [
            {
                "finding_id": "R2-1-001",
                "change_made": "Defined bar in §3.3.",
                "additional_affected_slices": [],
            }
        ],
        "self_review": [
            {
                "finding_id": "R2-1-001",
                "resolved": True,
                "over_specified": False,
                "introduces_contradiction": False,
                "notes": "ok",
            }
        ],
        "adjudication_summary": {"accepted": 1, "rejected": 0},
        "finding_lineage": [carry_forward, fresh_2a],
    }
    (artifact_dir / "round-2b.json").write_text(json.dumps(round_2b))

    out5 = run(
        READ,
        [
            "--slug",
            "foo",
            "--artifact-type",
            "spec",
            "--dispatch-bundle",
            "--stage",
            "3a",
            "--agent-id",
            "5",
        ],
        cwd=host,
    )
    assert out5.returncode == 0, out5.stderr
    bundle5 = json.loads(out5.stdout)
    summary = bundle5["global_summary"]
    # Lineage has 2 rows (one 1b carry-forward + one fresh 2a). The summary
    # must reflect the bundle's full edit footprint, not settle.accepted's
    # 2b-only count of 1.
    assert summary["accepted_findings_count"] == 2
    assert len(summary["edit_locations_compact"]) == 2
    assert summary["accepted_findings_count"] == len(summary["edit_locations_compact"])


def test_paste_rejects_fast_lineage_into_legacy_state(tmp_path):
    """A 1b envelope produced under fast/patch carries `finding_lineage`. If
    the receiving host is legacy/thorough (mode and review_profile unset),
    the local writer would NEVER emit that field. Accepting the paste
    persists a shape the local writer cannot produce, breaking cross-host
    parity and weakening legacy/thorough guarantees. The settle paste must
    be rejected."""
    host_a = tmp_path / "A"
    host_b = tmp_path / "B"
    host_a.mkdir()
    host_b.mkdir()
    _make_workspace(host_a)
    _make_workspace(host_b)

    # Host A: fast/patch with lineage.
    assert _init_fast_patch(host_a).returncode == 0
    assert _write_1a_fast_patch(host_a).returncode == 0
    assert _write_1b_fast_patch_accept(host_a).returncode == 0
    settled_1b = json.loads((host_a / ".cross-agent-reviews/foo/spec/round-1b.json").read_bytes())
    # Sanity: fast/patch writer emits finding_lineage.
    assert "finding_lineage" in settled_1b

    # Host B: legacy/thorough (no mode, no review_profile).
    assert _init_legacy(host_b).returncode == 0

    round_1a_bytes = (host_a / ".cross-agent-reviews/foo/spec/round-1a.json").read_bytes()
    paste_1a = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=round_1a_bytes.decode())
    assert paste_1a.returncode == 0, paste_1a.stderr

    paste_1b = run(READ, ["--paste", "--slug", "foo"], cwd=host_b, stdin=json.dumps(settled_1b))
    assert paste_1b.returncode != 0
    assert "lineage" in paste_1b.stderr.lower()
