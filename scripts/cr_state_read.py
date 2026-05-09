#!/usr/bin/env python3
"""Read state and round files, run integrity, paste-import, and spec-drift checks."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import jsonschema
from jsonschema import Draft202012Validator

from scripts._cr_lib import (
    atomic_write,
    build_registry,
    canonical_json,
    compute_content_hash,
    find_repo_root,
    load_schema,
    now_iso8601_utc,
    state_dir,
)

# Reuse the same cross-round invariant checks `cr_state_write.py` runs on
# locally-emitted envelopes. A schema-valid paste can still be locally
# impossible (e.g., a 2a payload missing verifications for accepted 1b
# findings, or any 2a/3a payload whose `slice_plan` diverges from the prior
# audit round). Replaying these on import keeps cross-host state in lockstep
# with what local writes would have produced.
from scripts.cr_state_write import (
    SETTLE_STAGES,
    _check_slice_plan_frozen,
    _cross_round_check_2a,
)

ROUND_STAGES = ("1a", "1b", "2a", "2b", "3a", "3b")


def _err(msg: str, *, code: int = 1) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def _read_round_files(artifact_dir: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not artifact_dir.exists():
        return out
    for stage in ROUND_STAGES:
        rp = artifact_dir / f"round-{stage}.json"
        if rp.exists():
            out[stage] = json.loads(rp.read_text())
    return out


def _classify(state: dict, artifact_type: str, artifact_dir: Path) -> dict:
    block = state.get(artifact_type)
    if block is None:
        return {"integrity": "OK", "pending_import": False, "pending_stage": None}
    completed = block.get("completed_rounds", [])
    rounds_on_disk = _read_round_files(artifact_dir)
    issues: list[str] = []
    pending_stage: str | None = None
    # orphan round files
    for stage in ROUND_STAGES:
        rp = artifact_dir / f"round-{stage}.json"
        if rp.exists() and stage not in completed:
            target = rp.with_name(
                f".discard-{now_iso8601_utc().replace(':', '')}-round-{stage}.json"
            )
            rp.rename(target)
            issues.append("ORPHAN_DISCARDED")
    # pending import: completed has a stage whose file is missing
    for stage in completed:
        if stage not in rounds_on_disk:
            pending_stage = stage
            break
    # integrity (only if some completed rounds have local files)
    locally_present = [r for r in rounds_on_disk.values() if r.get("stage") in completed]
    if locally_present:
        local_max = max(r["emitted_at"] for r in locally_present)
        if block["last_updated_at"] < local_max:
            return {
                "integrity": "STATE_INTEGRITY_ERROR",
                "pending_import": pending_stage is not None,
                "pending_stage": pending_stage,
            }
    return {
        "integrity": "ORPHAN_DISCARDED" if "ORPHAN_DISCARDED" in issues else "OK",
        "pending_import": pending_stage is not None,
        "pending_stage": pending_stage,
    }


def _cmd_read(repo_root: Path, slug: str, artifact_type: str) -> int:
    state_path = state_dir(repo_root) / slug / "state.json"
    if not state_path.exists():
        return _err(f"no state for slug {slug!r}")
    state = json.loads(state_path.read_text())
    artifact_dir = state_dir(repo_root) / slug / artifact_type
    classification = _classify(state, artifact_type, artifact_dir)
    if classification["integrity"] == "STATE_INTEGRITY_ERROR":
        sys.stdout.write(canonical_json({"state": state, **classification}))
        return _err("STATE_INTEGRITY_ERROR: state.last_updated_at < max round emitted_at", code=3)
    sys.stdout.write(canonical_json({"state": state, **classification}))
    return 0


def _cmd_check_spec_drift(repo_root: Path, slug: str) -> int:
    state_path = state_dir(repo_root) / slug / "state.json"
    state = json.loads(state_path.read_text())
    plan = state.get("plan")
    if plan is None or "spec_hash_at_start" not in plan:
        sys.stdout.write(canonical_json({"spec_drift": False, "reason": "no plan or no anchor"}))
        return 0
    spec_path = repo_root / state["spec"]["path"]
    current_hash = compute_content_hash(spec_path)
    drift = current_hash != plan["spec_hash_at_start"]
    payload = {"spec_drift": drift, "anchor": plan["spec_hash_at_start"], "current": current_hash}
    sys.stdout.write(canonical_json(payload))
    if drift:
        print("SPEC_DRIFT_DETECTED", file=sys.stderr)
        return 2
    return 0


def _cmd_resolve_drift(repo_root: Path, slug: str, mode: str) -> int:
    """Scripted recovery for spec drift (§7.8 of the design).

    `accept` refreshes `state.plan.spec_hash_at_start` to the current spec
    hash so the in-flight plan review can continue. `restart` archives the
    plan/ subdirectory and removes `state.plan` from state.json so the
    operator can re-run `cr_state_init.py --artifact-type plan` against
    the now-current spec. Both modes are atomic at the state.json layer.
    `abort` is the third option from §7.8 and requires no script — the
    router simply halts."""
    state_path = state_dir(repo_root) / slug / "state.json"
    if not state_path.exists():
        return _err(f"no state.json for slug {slug!r}")
    state = json.loads(state_path.read_text())
    plan = state.get("plan")
    if plan is None:
        return _err(f"no plan block for slug {slug!r}; nothing to resolve")
    spec = state.get("spec")
    if spec is None:
        return _err(f"slug {slug!r} has no spec block; cannot resolve drift")
    if mode == "accept":
        spec_path = repo_root / spec["path"]
        current_hash = compute_content_hash(spec_path)
        plan["spec_hash_at_start"] = current_hash
        plan["last_updated_at"] = now_iso8601_utc()
        state["plan"] = plan
        atomic_write(state_path, canonical_json(state))
        sys.stdout.write(canonical_json(state))
        return 0
    if mode == "restart":
        plan_dir = state_dir(repo_root) / slug / "plan"
        archive = state_dir(repo_root) / slug / f".archive-{now_iso8601_utc().replace(':', '')}"
        if plan_dir.exists():
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(plan_dir), str(archive / "plan"))
        del state["plan"]
        atomic_write(state_path, canonical_json(state))
        sys.stdout.write(canonical_json(state))
        return 0
    return _err(f"unknown drift-resolution mode: {mode!r}; use 'accept' or 'restart'")


def _paste_cross_round_invariants(envelope: dict, artifact_dir: Path) -> str | None:
    """Apply the cross-round checks that `cr_state_write.py` runs locally.

    For 2a: verifications must reference accepted 1b findings with the
    correct frozen-slice ownership. For 2a/3a: the `slice_plan` must match
    the prior audit round's slice plan. For 1b/2b/3b: the same per-envelope
    settle invariants `_build_settle_envelope` enforces locally — every
    paired-audit finding has exactly one adjudication, every accepted finding
    has matching changelog and self_review entries, and every adjudication /
    changelog / self_review finding_id resolves into the paired audit (or, for
    2b only, the paired 2a's `round_1_verifications`). Returns an error
    message string on failure, or None when the envelope passes."""
    stage = envelope["stage"]
    if stage == "2a":
        prior_1b = _read_optional(artifact_dir / "round-1b.json")
        if prior_1b is None:
            return "cannot verify 2a paste: prior round-1b.json is not on disk"
        err = _cross_round_check_2a(envelope, prior_1b)
        if err is not None:
            return err
        prior_1a = _read_optional(artifact_dir / "round-1a.json")
        if prior_1a is not None:
            err = _check_slice_plan_frozen(envelope, prior_1a)
            if err is not None:
                return err
    elif stage == "3a":
        prior_2a = _read_optional(artifact_dir / "round-2a.json")
        if prior_2a is not None:
            err = _check_slice_plan_frozen(envelope, prior_2a)
            if err is not None:
                return err
    elif stage in {"1b", "2b", "3b"}:
        # Settle paste: replay the same envelope-level invariants that
        # `_build_settle_envelope` enforces on local writes. Schema
        # validation alone misses these because they span three top-level
        # arrays AND require cross-referencing the paired audit. Without
        # this branch a schema-valid pasted 1b/2b/3b envelope can omit
        # adjudications, accept findings without changelog/self_review
        # evidence, or reference unknown finding ids and still advance
        # local state — diverging cross-host behaviour from local-write
        # behaviour and breaking the contract that paste reproduces what
        # local writes would have produced.
        paired_audit_stage = {"1b": "1a", "2b": "2a", "3b": "3a"}[stage]
        paired_audit = _read_optional(artifact_dir / f"round-{paired_audit_stage}.json")
        if paired_audit is None:
            return (
                f"cannot verify {stage} paste: paired round-{paired_audit_stage}.json "
                "is not on disk"
            )
        err = _settle_paste_invariants(envelope, paired_audit)
        if err is not None:
            return err
    return None


def _settle_paste_invariants(envelope: dict, paired_audit: dict) -> str | None:
    """Envelope-level settle invariants, replayed on paste.

    Mirrors the checks in `cr_state_write.py::_build_settle_envelope` but
    operates on a complete envelope (paste path) rather than a raw payload
    (build path). Kept as a sibling to the build-time logic instead of
    refactoring both into one shared helper because the build path consumes
    raw payload fields while the paste path consumes envelope fields, and
    bridging the two would require constructing synthetic envelopes during
    build — a larger change than this finding warrants. Any future change
    to the build-time invariants MUST be mirrored here; the test suite for
    `cr_state_read.py` covers each invariant via a dedicated paste-failure
    case (see Step 1 fixtures `bad_paste_settle_*`).

    Coverage includes the derived-field invariants `_build_settle_envelope`
    synthesizes locally (`accepted_findings`, `rejected_findings`,
    `adjudication_summary`, and 3b's `final_status`): a hand-built paste
    can be schema-valid yet diverge from what a local write would produce,
    so each derived field is replayed against the adjudications + audit and
    rejected on mismatch. Without these checks, a paste could advance state
    with empty `accepted_findings` while accepting findings via
    `adjudications` — silently breaking the downstream 2a verifier (which
    reads `accepted_findings` to know what to verify)."""
    audit_findings_by_id: dict[str, dict] = {}
    for agent in paired_audit["agents"]:
        for finding in agent["findings"]:
            audit_findings_by_id[finding["id"]] = finding
    audit_finding_ids = set(audit_findings_by_id.keys())

    # 2b additionally permits changelog / self_review finding_ids sourced
    # from the paired 2a's `round_1_verifications` (revisited 1b
    # corrections). Adjudications still must reference 2a NEW findings only.
    revisit_finding_ids: set[str] = set()
    if envelope["stage"] == "2b":
        for agent in paired_audit["agents"]:
            for v in agent.get("round_1_verifications", []):
                revisit_finding_ids.add(v["round_1_finding_id"])
    allowed_edit_ids = audit_finding_ids | revisit_finding_ids

    adjudication_id_list = [a["finding_id"] for a in envelope["adjudications"]]
    unknown_adj = [fid for fid in adjudication_id_list if fid not in audit_findings_by_id]
    if unknown_adj:
        return f"adjudication finding_id(s) not present in paired audit: {unknown_adj}"
    adjudication_id_set = set(adjudication_id_list)
    missing_adj = sorted(audit_finding_ids - adjudication_id_set)
    if missing_adj:
        return f"audit finding(s) missing an adjudication: {missing_adj}"
    duplicate_adj = sorted(
        {fid for fid in adjudication_id_list if adjudication_id_list.count(fid) > 1}
    )
    if duplicate_adj:
        return f"audit finding(s) with multiple adjudications: {duplicate_adj}"

    unknown_changelog = [
        c["finding_id"] for c in envelope["changelog"] if c["finding_id"] not in allowed_edit_ids
    ]
    if unknown_changelog:
        return (
            "changelog finding_id(s) not present in paired audit "
            f"or round_1_verifications: {unknown_changelog}"
        )
    unknown_review = [
        s["finding_id"] for s in envelope["self_review"] if s["finding_id"] not in allowed_edit_ids
    ]
    if unknown_review:
        return (
            "self_review finding_id(s) not present in paired audit "
            f"or round_1_verifications: {unknown_review}"
        )

    accepted_set = {a["finding_id"] for a in envelope["adjudications"] if a["verdict"] == "accept"}
    rejected_set = {a["finding_id"] for a in envelope["adjudications"] if a["verdict"] == "reject"}
    changelog_ids = {c["finding_id"] for c in envelope["changelog"]}
    self_review_ids = {s["finding_id"] for s in envelope["self_review"]}
    missing_changelog = sorted(accepted_set - changelog_ids)
    if missing_changelog:
        return f"accepted finding(s) missing a changelog entry: {missing_changelog}"
    missing_self_review = sorted(accepted_set - self_review_ids)
    if missing_self_review:
        return f"accepted finding(s) missing a self_review entry: {missing_self_review}"

    # Derived-field consistency. `cr_state_write.py::_build_settle_envelope`
    # synthesizes `accepted_findings`, `rejected_findings`,
    # `adjudication_summary`, and (for 3b) `final_status` from the
    # adjudications + paired audit. A schema-valid pasted settle envelope
    # could omit or mis-populate these fields, advancing local state with
    # an envelope that diverges from what a local write would have produced
    # and breaking downstream verification (which reads `accepted_findings`
    # to know what to verify). Replay the same derivations here.
    accepted_envelope_ids = {f["id"] for f in envelope["accepted_findings"]}
    if accepted_envelope_ids != accepted_set:
        return (
            f"accepted_findings id set {sorted(accepted_envelope_ids)} "
            f"diverges from adjudications (accept verdicts) "
            f"{sorted(accepted_set)}"
        )
    rejected_envelope_ids = {f["id"] for f in envelope["rejected_findings"]}
    if rejected_envelope_ids != rejected_set:
        return (
            f"rejected_findings id set {sorted(rejected_envelope_ids)} "
            f"diverges from adjudications (reject verdicts) "
            f"{sorted(rejected_set)}"
        )
    summary = envelope["adjudication_summary"]
    if summary.get("accepted") != len(accepted_envelope_ids):
        return (
            f"adjudication_summary.accepted={summary.get('accepted')} "
            f"diverges from accepted_findings count "
            f"{len(accepted_envelope_ids)}"
        )
    if summary.get("rejected") != len(rejected_envelope_ids):
        return (
            f"adjudication_summary.rejected={summary.get('rejected')} "
            f"diverges from rejected_findings count "
            f"{len(rejected_envelope_ids)}"
        )
    if envelope["stage"] == "3b":
        expected_final = (
            "CORRECTED_AND_READY" if accepted_envelope_ids else "READY_FOR_IMPLEMENTATION"
        )
        if envelope.get("final_status") != expected_final:
            return (
                f"final_status={envelope.get('final_status')!r} diverges "
                f"from accepted_findings shape (expected {expected_final!r})"
            )
    return None


def _read_optional(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def _cmd_paste(repo_root: Path, slug: str, raw: str) -> int:
    try:
        instance = json.loads(raw)
    except json.JSONDecodeError as e:
        return _err(f"invalid JSON: {e}")
    registry = build_registry(repo_root)
    is_bootstrap = (
        "schema_version" in instance
        and ("spec" in instance or "plan" in instance)
        and "stage" not in instance
    )
    state_path = state_dir(repo_root) / slug / "state.json"
    if is_bootstrap:
        if state_path.exists():
            return _err(f"refusing to clobber existing state.json for slug {slug!r}")
        schema = load_schema(repo_root, "state.schema.json")
        try:
            Draft202012Validator(schema, registry=registry).validate(instance)
        except jsonschema.ValidationError as e:
            return _err(f"state schema violation: {e.message}")
        # Both-block invariant: state.schema.json cannot conditionally require
        # `state.plan.spec_hash_at_start` only when both blocks exist. Without
        # this script-level check, a schema-valid pasted state with both blocks
        # but no anchor would silently disable spec-drift protection because
        # `_cmd_check_spec_drift` treats a missing anchor as non-drift. The
        # same invariant is re-enforced in `cr_state_write.py` at every round
        # entry; rejecting it at paste time keeps the diagnostic local rather
        # than surfacing only after a round envelope is built.
        if (
            "spec" in instance
            and "plan" in instance
            and "spec_hash_at_start" not in instance.get("plan", {})
        ):
            return _err(
                "state integrity: pasted state has both 'spec' and 'plan' "
                "blocks but plan.spec_hash_at_start is missing (would silently "
                "bypass spec-drift detection)."
            )
        if instance.get("slug") != slug:
            return _err(
                f"slug mismatch: state.json has {instance.get('slug')!r}, --slug says {slug!r}"
            )
        # First-time bootstrap on a fresh host: `<state_dir>/<slug>/` does
        # not exist yet, but `atomic_write` writes a sibling tempfile and
        # `os.replace`s it into place — both require the destination
        # directory to exist. The round-paste branch below already does
        # the same `mkdir` for `artifact_dir`; without this the very first
        # `--paste --slug <s>` call against a clean clone fails with
        # `FileNotFoundError` before any state is written.
        state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(state_path, canonical_json(instance))
        sys.stdout.write(canonical_json(instance))
        return 0

    # Round paste
    if not state_path.exists():
        return _err(f"no local state.json for slug {slug!r}; bootstrap first")
    state = json.loads(state_path.read_text())
    is_audit = "agents" in instance
    schema_name = "round-audit.schema.json" if is_audit else "round-settle.schema.json"
    schema = load_schema(repo_root, schema_name)
    try:
        Draft202012Validator(schema, registry=registry).validate(instance)
    except jsonschema.ValidationError as e:
        return _err(f"round schema violation: {e.message}")
    if instance["slug"] != slug:
        return _err(f"slug mismatch: paste has {instance['slug']!r}, --slug says {slug!r}")
    artifact_type = instance["artifact_type"]
    block = state.get(artifact_type)
    if block is None or instance["artifact_path"] != block["path"]:
        return _err("artifact_path mismatch with local state.json")
    expected_stage = block["current_stage"].replace("round_", "").replace("_pending", "")
    artifact_dir = state_dir(repo_root) / slug / artifact_type
    artifact_dir.mkdir(parents=True, exist_ok=True)
    # Pending-import override: earliest completed-but-missing stage
    rounds_on_disk = _read_round_files(artifact_dir)
    pending = next((s for s in block["completed_rounds"] if s not in rounds_on_disk), None)
    if pending is not None:
        expected_stage = pending
    if instance["stage"] != expected_stage:
        return _err(f"stage mismatch: expected {expected_stage!r}, paste has {instance['stage']!r}")
    # Cross-round invariants: replay the same checks `cr_state_write.py`
    # applies to local writes so a schema-valid but locally-impossible paste
    # is rejected before it touches disk. Required prior round files must be
    # available locally (the pending-import branch above already confirmed
    # `completed_rounds` and the on-disk round files agree).
    invariant_err = _paste_cross_round_invariants(instance, artifact_dir)
    if invariant_err is not None:
        return _err(invariant_err)
    body = canonical_json(instance)
    atomic_write(artifact_dir / f"round-{instance['stage']}.json", body)
    if pending is None:
        block["completed_rounds"] = sorted({*block["completed_rounds"], instance["stage"]})
        next_stage = {
            "1a": "round_1b_pending",
            "1b": "round_2a_pending",
            "2a": "round_2b_pending",
            "2b": "round_3a_pending",
            "3a": "round_3b_pending",
            "3b": "ready_for_implementation",
        }[instance["stage"]]
        block["current_stage"] = next_stage
        block["last_updated_at"] = instance["emitted_at"]
        # Settle stages (1b/2b/3b) ship post-edit artifact bytes alongside
        # the envelope; refresh content_hash from the local artifact so a
        # later plan-init under the same slug anchors to the post-edit hash.
        # Mirrors the local-write refresh in cr_state_write.py — both write
        # paths must apply this invariant or cross-host state diverges from
        # local-only state for the same logical settle round.
        if instance["stage"] in SETTLE_STAGES:
            block["content_hash"] = compute_content_hash(repo_root / block["path"])
        state[artifact_type] = block
        atomic_write(state_path, canonical_json(state))
    sys.stdout.write(body)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument("--artifact-type", choices=["spec", "plan"])
    p.add_argument("--check-spec-drift", action="store_true")
    p.add_argument(
        "--resolve-drift",
        choices=["accept", "restart"],
        help="Apply the §7.8 drift-recovery the operator chose.",
    )
    p.add_argument("--paste", action="store_true")
    args = p.parse_args()

    repo_root = find_repo_root(Path.cwd())
    if args.paste:
        return _cmd_paste(repo_root, args.slug, sys.stdin.read())
    if args.resolve_drift:
        return _cmd_resolve_drift(repo_root, args.slug, args.resolve_drift)
    if args.check_spec_drift:
        return _cmd_check_spec_drift(repo_root, args.slug)
    if args.artifact_type is None:
        return _err("--artifact-type required for read mode")
    return _cmd_read(repo_root, args.slug, args.artifact_type)


if __name__ == "__main__":
    sys.exit(main())
