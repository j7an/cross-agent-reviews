#!/usr/bin/env python3
"""Read state and round files, run integrity, paste-import, and spec-drift checks."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import jsonschema
from _cr_lib import (
    CLEAN_3A_TERMINAL,
    VIA_3B_TERMINAL,
    atomic_write,
    build_registry,
    canonical_json,
    compute_content_hash,
    find_repo_root,
    load_schema,
    now_iso8601_utc,
    state_dir,
    terminal_shape,
    validate_slug,
)

# Reuse the same cross-round invariant checks `cr_state_write.py` runs on
# locally-emitted envelopes. A schema-valid paste can still be locally
# impossible (e.g., a 2a payload missing verifications for accepted 1b
# findings, or any 2a/3a payload whose `slice_plan` diverges from the prior
# audit round). Replaying these on import keeps cross-host state in lockstep
# with what local writes would have produced.
from cr_state_write import (
    SETTLE_STAGES,
    _check_slice_plan_frozen,
    _cross_round_check_2a,
    _is_clean_3a,
)
from jsonschema import Draft202012Validator

ROUND_STAGES = ("1a", "1b", "2a", "2b", "3a", "3b")


def _err(msg: str, *, code: int = 1) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def _read_round_files(artifact_dir: Path) -> dict[str, dict]:
    """Read round-{stage}.json files into a dict keyed by stage.

    Side effect: a malformed round file (one that fails `json.loads`) is
    renamed aside to `.discard-<ts>-malformed-round-<stage>.json` and a
    warning is emitted on stderr. The malformed entry is omitted from the
    return value so downstream classification (`_classify`) treats it as
    absent — the existing pending-import logic then surfaces it naturally
    if the stage is in `completed_rounds`. The `malformed-` infix is
    distinct from the orphan-discard prefix used at `_classify:65-73` so an
    operator inspecting the directory can tell the two recovery kinds apart.
    Adopting the rename here (rather than in `_classify`) means `_classify`
    can rely on `rounds_on_disk` being well-formed."""
    out: dict[str, dict] = {}
    if not artifact_dir.exists():
        return out
    for stage in ROUND_STAGES:
        rp = artifact_dir / f"round-{stage}.json"
        if not rp.exists():
            continue
        try:
            out[stage] = json.loads(rp.read_text())
        except json.JSONDecodeError:
            target = rp.with_name(
                f".discard-{now_iso8601_utc().replace(':', '')}-malformed-round-{stage}.json"
            )
            rp.rename(target)
            print(
                f"WARNING: malformed round file at {rp}; renamed to {target}",
                file=sys.stderr,
            )
    return out


def _classify(state: dict, artifact_type: str, artifact_dir: Path) -> dict:
    block = state.get(artifact_type)
    if block is None:
        return {
            "integrity": "OK",
            "integrity_reason": None,
            "pending_import": False,
            "pending_stage": None,
        }
    completed = block.get("completed_rounds", [])
    # Invalid terminal shape: ready_for_implementation with a completed_rounds
    # set that is neither terminal shape. An integrity error invalidates every
    # subsequent routing decision, so this is checked before pending-import
    # detection (consistent with SKILL.md §2's "check this before any other
    # branch").
    if (
        block.get("current_stage") == "ready_for_implementation"
        and terminal_shape(completed) == "invalid"
    ):
        return {
            "integrity": "STATE_INTEGRITY_ERROR",
            "integrity_reason": "invalid_terminal_shape",
            "pending_import": False,
            "pending_stage": None,
        }
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
                "integrity_reason": "stale_state",
                "pending_import": pending_stage is not None,
                "pending_stage": pending_stage,
            }
    return {
        "integrity": "ORPHAN_DISCARDED" if "ORPHAN_DISCARDED" in issues else "OK",
        "integrity_reason": None,
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
    sys.stdout.write(canonical_json({"state": state, **classification}))
    if classification["integrity"] == "STATE_INTEGRITY_ERROR":
        if classification["integrity_reason"] == "invalid_terminal_shape":
            return _err(
                "STATE_INTEGRITY_ERROR: current_stage is ready_for_implementation "
                "but completed_rounds is neither terminal shape",
                code=3,
            )
        return _err("STATE_INTEGRITY_ERROR: state.last_updated_at < max round emitted_at", code=3)
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
    revisit_verification_status: dict[str, str] = {}
    if envelope["stage"] == "2b":
        for agent in paired_audit["agents"]:
            for v in agent.get("round_1_verifications", []):
                fid = v["round_1_finding_id"]
                revisit_finding_ids.add(fid)
                revisit_verification_status[fid] = v["status"]
    allowed_edit_ids = audit_finding_ids | revisit_finding_ids

    # M4 invariants for 2b revisit entries — mirrors the build-side checks
    # in `cr_state_write.py::_build_settle_envelope`. Without these the
    # paste path accepts what a local write rejects, breaking the cross-
    # host parity contract (§10.3): a 2b author could ship a revisit
    # changelog without a paired self_review (or revisit an already-
    # resolved verification) on host A, locally rejected, then paste the
    # same envelope onto host B and have it land schema-valid.
    if envelope["stage"] == "2b":
        revisit_changelog_ids = {
            c["finding_id"] for c in envelope["changelog"] if c["finding_id"] in revisit_finding_ids
        }
        revisit_self_review_ids = {
            s["finding_id"]
            for s in envelope["self_review"]
            if s["finding_id"] in revisit_finding_ids
        }
        revisit_changelog_only = sorted(revisit_changelog_ids - revisit_self_review_ids)
        revisit_self_review_only = sorted(revisit_self_review_ids - revisit_changelog_ids)
        if revisit_changelog_only or revisit_self_review_only:
            return (
                "2b revisit changelog and self_review must be paired 1:1; "
                f"changelog without self_review: {revisit_changelog_only}; "
                f"self_review without changelog: {revisit_self_review_only}"
            )
        revisit_payload_ids = revisit_changelog_ids | revisit_self_review_ids
        already_resolved = sorted(
            fid for fid in revisit_payload_ids if revisit_verification_status.get(fid) == "resolved"
        )
        if already_resolved:
            return f"2b revisit references already-resolved verification(s): {already_resolved}"

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
    #
    # Equality is full parsed-object comparison, not just id membership: the
    # writer derives each finding object from the paired audit, so a paste
    # that keeps a correct id but mutates an embedded field (`severity`,
    # `finding`, `location`, a rejection reason) or reorders the arrays must
    # be rejected. Python `dict`/`list` `==` compares structure and element
    # order, which is exactly the intended contract. `unknown_adj` above
    # guarantees every adjudication id is in `audit_findings_by_id`, and the
    # duplicate-adjudication check guarantees `adj_by_id` is well-defined.
    adj_by_id = {a["finding_id"]: a for a in envelope["adjudications"]}
    accept_ids_ordered = [
        a["finding_id"] for a in envelope["adjudications"] if a["verdict"] == "accept"
    ]
    reject_ids_ordered = [
        a["finding_id"] for a in envelope["adjudications"] if a["verdict"] == "reject"
    ]
    expected_accepted = [audit_findings_by_id[fid] for fid in accept_ids_ordered]
    expected_rejected = [
        {**audit_findings_by_id[fid], "rejection_reason": adj_by_id[fid]["reasoning"]}
        for fid in reject_ids_ordered
    ]
    if envelope["accepted_findings"] != expected_accepted:
        return (
            "accepted_findings diverges from the paired-audit derivation "
            "(content or order mismatch with adjudications + paired audit)"
        )
    if envelope["rejected_findings"] != expected_rejected:
        return (
            "rejected_findings diverges from the paired-audit derivation "
            "(content, rejection_reason, or order mismatch with "
            "adjudications + paired audit)"
        )
    summary = envelope["adjudication_summary"]
    if summary.get("accepted") != len(expected_accepted):
        return (
            f"adjudication_summary.accepted={summary.get('accepted')} "
            f"diverges from accepted_findings count {len(expected_accepted)}"
        )
    if summary.get("rejected") != len(expected_rejected):
        return (
            f"adjudication_summary.rejected={summary.get('rejected')} "
            f"diverges from rejected_findings count {len(expected_rejected)}"
        )
    if envelope["stage"] == "3b":
        expected_final = "CORRECTED_AND_READY" if expected_accepted else "READY_FOR_IMPLEMENTATION"
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
    registry = build_registry()
    is_bootstrap = (
        "schema_version" in instance
        and ("spec" in instance or "plan" in instance)
        and "stage" not in instance
    )
    state_path = state_dir(repo_root) / slug / "state.json"
    if is_bootstrap:
        if state_path.exists():
            return _err(f"refusing to clobber existing state.json for slug {slug!r}")
        schema = load_schema("state.schema.json")
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
        # Impossible-transition invariant: a fresh bootstrap is either a
        # brand-new pipeline (`round_1a_pending` + no completed rounds) or
        # a terminal cross-host handoff (`ready_for_implementation` + all
        # six rounds completed). Anything else — e.g. `round_3a_pending`
        # with empty completed_rounds — is schema-valid but locally
        # impossible: routing on it would jump to round 3a with no prior
        # round files on disk, surfacing as cascading errors far from the
        # root cause. The schema cannot express this cleanly (per-stage
        # if/then). Catch it at paste time, naming the offending block.
        for block_name in ("spec", "plan"):
            block = instance.get(block_name)
            if block is None:
                continue
            stage = block.get("current_stage")
            completed = block.get("completed_rounds", [])
            if stage == "round_1a_pending":
                if completed:
                    return _err(
                        f"state integrity: bootstrap state.{block_name} has "
                        f"current_stage='round_1a_pending' but "
                        f"completed_rounds={completed!r} (must be [])"
                    )
            elif stage == "ready_for_implementation":
                if terminal_shape(completed) == "invalid":
                    return _err(
                        f"state integrity: bootstrap state.{block_name} has "
                        f"current_stage='ready_for_implementation' but "
                        f"completed_rounds={completed!r} (must be the clean-3a "
                        f"terminal {sorted(CLEAN_3A_TERMINAL)} or the via-3b "
                        f"terminal {sorted(VIA_3B_TERMINAL)})"
                    )
            else:
                return _err(
                    f"state integrity: bootstrap state.{block_name} has "
                    f"current_stage={stage!r} which is not legal for a fresh "
                    "bootstrap (must be 'round_1a_pending' with empty "
                    "completed_rounds, or 'ready_for_implementation' with "
                    "all rounds completed)"
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
    schema = load_schema(schema_name)
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
        if instance["stage"] == "3a" and _is_clean_3a(instance):
            next_stage = "ready_for_implementation"
        else:
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

    try:
        validate_slug(args.slug)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

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
