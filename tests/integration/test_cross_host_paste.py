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
