#!/usr/bin/env python3
"""Build, validate, and persist the canonical round envelope.

Inputs come from --input (JSON file with stage + per-stage payload). The
script auto-assigns finding IDs, copies the slice_plan from the prior
audit round, computes adjudication_summary, derives final_status for 3b,
runs JSON Schema validation, runs cross-round invariants, atomically
writes the round file, updates state.json, and emits byte-identical JSON
to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema
from _cr_lib import (
    atomic_write,
    build_registry,
    canonical_json,
    compute_content_hash,
    err,
    find_repo_root,
    load_schema,
    now_iso8601_utc,
    state_dir,
    validate_slug,
)
from jsonschema import Draft202012Validator

STAGE_TO_ROUND = {"1a": 1, "1b": 1, "2a": 2, "2b": 2, "3a": 3, "3b": 3, "3c": 3}
AUDIT_STAGES = {"1a", "2a", "3a"}
SETTLE_STAGES = {"1b", "2b", "3b"}
VERIFY_STAGES = {"3c"}
NEXT_STAGE = {
    "1a": "round_1b_pending",
    "1b": "round_2a_pending",
    "2a": "round_2b_pending",
    "2b": "round_3a_pending",
    "3a": "round_3b_pending",
    "3b": "ready_for_implementation",
}


def _is_clean_3a(envelope: dict) -> bool:
    """True when every agent in a 3a envelope is ship_ready (zero findings).

    Per round-audit.schema.json, ship_ready implies an empty findings list, so
    'all agents ship_ready' is equivalent to 'combined findings empty'. status
    is the single authoritative field, so it is what we check.
    """
    return all(a["status"] == "ship_ready" for a in envelope["agents"])


def _is_clean_1a(envelope: dict) -> bool:
    """True when every agent in a 1a envelope is `clean` (⇒ zero findings)."""
    return all(a["status"] == "clean" for a in envelope["agents"])


def _is_clean_2a(envelope: dict) -> bool:
    """True when a 2a envelope is clean: every agent `verified`, zero new
    findings, and every round-1 verification `resolved`."""
    if not all(a["status"] == "verified" for a in envelope["agents"]):
        return False
    if any(a["findings"] for a in envelope["agents"]):
        return False
    return all(
        v["status"] == "resolved" for a in envelope["agents"] for v in a["round_1_verifications"]
    )


def _attempt_files(artifact_dir: Path) -> list[dict]:
    """Return parsed round-3c-attempt-*.json envelopes, sorted by attempt_number.

    Failed-attempt files are host-local working evidence. They are read for the
    rerun guard, the next attempt_number, and the prior_attempts summary; they
    are never paste-imported and never tracked in completed_rounds.
    """
    out: list[dict] = []
    if not artifact_dir.exists():
        return out
    for path in artifact_dir.glob("round-3c-attempt-*.json"):
        out.append(json.loads(path.read_text()))
    out.sort(key=lambda e: e["attempt_number"])
    return out


def _prior_attempt_summary(attempt: dict) -> dict:
    """One prior_attempts entry summarizing a failed round-3c-attempt-*.json."""
    return {
        "attempt_number": attempt["attempt_number"],
        "verified_content_hash": attempt["verified_content_hash"],
        "not_resolved_finding_ids": [
            v["round_3a_finding_id"]
            for v in attempt["verifications"]
            if v["status"] == "not_resolved"
        ],
        "regression_count": len(attempt["regression_findings"]),
        "emitted_at": attempt["emitted_at"],
    }


def _check_verification_set(
    verifications: list[dict], accepted_3b_findings: list[dict]
) -> str | None:
    """1:1 invariant: verifications cover exactly the accepted 3a blockers.

    Shared with cr_state_read.py's 3c paste path so a pasted 3c envelope is
    held to the same standard as a locally-built one. Returns an error message
    on mismatch, else None.
    """
    expected = {f["id"] for f in accepted_3b_findings}
    seen: list[str] = [v["round_3a_finding_id"] for v in verifications]
    seen_set = set(seen)
    if len(seen) != len(seen_set):
        dups = sorted({fid for fid in seen if seen.count(fid) > 1})
        return f"3c has duplicate verification(s) for finding id(s): {dups}"
    missing = sorted(expected - seen_set)
    if missing:
        return f"3c is missing a verification for accepted 3a blocker(s): {missing}"
    extra = sorted(seen_set - expected)
    if extra:
        return f"3c verifies finding id(s) not accepted by 3b: {extra}"
    return None


def _assign_finding_ids(round_num: int, agents: list[dict]) -> None:
    # Writer owns finding-ID generation outright: any caller-supplied `id`
    # value is overwritten so a stale or mis-scoped ID from an upstream paste
    # cannot leak into the canonical envelope. Direct assignment (not
    # setdefault) keeps the prose contract — "the script is the only place
    # that auto-assigns IDs" — actually true.
    for agent in agents:
        for idx, finding in enumerate(agent.get("findings", []), start=1):
            finding["id"] = f"R{round_num}-{agent['agent_id']}-{idx:03d}"


def _build_audit_envelope(
    slug: str, artifact_type: str, artifact_path: str, payload: dict, prior_audit: dict | None
) -> dict:
    stage = payload["stage"]
    round_num = STAGE_TO_ROUND[stage]
    if stage == "1a":
        slice_plan = payload["slice_plan"]
    else:
        if prior_audit is None:
            raise ValueError(
                f"Stage {stage} requires a prior audit round file to source slice_plan."
            )
        slice_plan = prior_audit["slice_plan"]
    agents = [dict(a) for a in payload["agents"]]
    # Cross-array invariant: agent_ids must be unique AND match the
    # slice_plan's agent_ids exactly. Without this check, duplicate or
    # missing agent reports produce schema-valid envelopes whose finding
    # IDs can collide (e.g., two agents both numbered 1 → both produce
    # `R1-1-001` for distinct findings, which silently breaks downstream
    # adjudication and verification matching).
    expected_agent_ids = sorted(s["agent_id"] for s in slice_plan)
    actual_agent_ids = sorted(a["agent_id"] for a in agents)
    if actual_agent_ids != expected_agent_ids:
        raise ValueError(
            "agent reports do not align with slice_plan: expected agent_ids "
            f"{expected_agent_ids}, got {actual_agent_ids}"
        )
    for a in agents:
        a.setdefault("round_1_verifications", [])
    _assign_finding_ids(round_num, agents)
    return {
        "round": round_num,
        "stage": stage,
        "schema_version": 1,
        "slug": slug,
        "artifact_type": artifact_type,
        "artifact_path": artifact_path,
        "emitted_at": now_iso8601_utc(),
        "slice_plan": slice_plan,
        "agents": agents,
    }


def _build_settle_envelope(
    slug: str,
    artifact_type: str,
    artifact_path: str,
    payload: dict,
    paired_audit: dict,
    prior_settle: dict | None,
) -> dict:
    stage = payload["stage"]
    round_num = STAGE_TO_ROUND[stage]

    # Index the paired audit findings so every adjudication / changelog /
    # self_review entry can be checked against a known id BEFORE we build
    # the envelope. Silently dropping unknown ids would let a typo or stale
    # finding id produce a schema-valid settle envelope whose summary,
    # accepted_findings, changelog, and final_status disagree.
    audit_findings_by_id: dict[str, dict] = {}
    for agent in paired_audit["agents"]:
        for finding in agent["findings"]:
            audit_findings_by_id[finding["id"]] = finding

    # Round 2b additionally permits changelog and self_review entries to
    # reference Round 1 finding IDs sourced from the paired 2a's
    # round_1_verifications when the 2b author chose to revisit an
    # unresolved correction (see 2b-settle.md §2). Adjudications still must
    # reference 2a NEW findings only — round_1_verifications are
    # informational and carry no Adjudication record per 2b §2.
    revisit_finding_ids: set[str] = set()
    revisit_verification_status: dict[str, str] = {}
    if stage == "2b":
        for agent in paired_audit["agents"]:
            for v in agent.get("round_1_verifications", []):
                fid = v["round_1_finding_id"]
                revisit_finding_ids.add(fid)
                revisit_verification_status[fid] = v["status"]

        # M4 invariant 1: revisit changelog↔self_review pairing. The
        # accepted-finding pairing rule below (lines 195-203) only enforces
        # 1:1 pairing for 2a NEW finding ids; revisit entries (changelog
        # and self_review entries whose finding_id is in the paired 2a's
        # round_1_verifications) need their own pairing check. Without it,
        # a 2b author can submit a revisit edit without recording the
        # matching self_review (or vice versa), breaking the audit trail
        # and dodging the same fix-before-emit standard adjudicated edits
        # already enforce.
        revisit_changelog_ids = {
            c["finding_id"] for c in payload["changelog"] if c["finding_id"] in revisit_finding_ids
        }
        revisit_self_review_ids = {
            s["finding_id"]
            for s in payload["self_review"]
            if s["finding_id"] in revisit_finding_ids
        }
        revisit_changelog_only = sorted(revisit_changelog_ids - revisit_self_review_ids)
        revisit_self_review_only = sorted(revisit_self_review_ids - revisit_changelog_ids)
        if revisit_changelog_only or revisit_self_review_only:
            raise ValueError(
                "2b revisit changelog and self_review must be paired 1:1; "
                f"changelog without self_review: {revisit_changelog_only}; "
                f"self_review without changelog: {revisit_self_review_only}"
            )

        # M4 invariant 2: revisits target only unresolved verifications. A
        # round_1_verification with status='resolved' is already settled by
        # the 2a reviewer; revisiting it would corrupt the audit trail by
        # appending a "fix" record to a correction that was already
        # confirmed effective. Per 2b-settle.md §2, revisits are only
        # legitimate when status != 'resolved'. Reject if any revisit-
        # bearing changelog or self_review entry references a finding_id
        # whose paired 2a verification is already resolved.
        revisit_payload_ids = revisit_changelog_ids | revisit_self_review_ids
        already_resolved = sorted(
            fid for fid in revisit_payload_ids if revisit_verification_status.get(fid) == "resolved"
        )
        if already_resolved:
            raise ValueError(
                f"2b revisit references already-resolved verification(s): {already_resolved}"
            )

    unknown_adj = [
        a["finding_id"]
        for a in payload["adjudications"]
        if a["finding_id"] not in audit_findings_by_id
    ]
    if unknown_adj:
        raise ValueError(f"adjudication finding_id(s) not present in paired audit: {unknown_adj}")
    allowed_edit_ids = audit_findings_by_id.keys() | revisit_finding_ids
    unknown_changelog = [
        c["finding_id"] for c in payload["changelog"] if c["finding_id"] not in allowed_edit_ids
    ]
    if unknown_changelog:
        raise ValueError(
            "changelog finding_id(s) not present in paired audit "
            f"or round_1_verifications: {unknown_changelog}"
        )
    unknown_review = [
        s["finding_id"] for s in payload["self_review"] if s["finding_id"] not in allowed_edit_ids
    ]
    if unknown_review:
        raise ValueError(
            "self_review finding_id(s) not present in paired audit "
            f"or round_1_verifications: {unknown_review}"
        )

    # Cross-round 1:1 invariant: every audit finding MUST have exactly one
    # adjudication, and no adjudication may appear twice. Without this check
    # a typo or omission silently drops an audit finding from the settle
    # round while still producing a schema-valid envelope (the schema cannot
    # see across rounds). The downstream verification round would then have
    # nothing to verify against for the dropped finding.
    audit_finding_ids = set(audit_findings_by_id.keys())
    adjudication_id_list = [a["finding_id"] for a in payload["adjudications"]]
    adjudication_id_set = set(adjudication_id_list)
    missing_adjudications = sorted(audit_finding_ids - adjudication_id_set)
    if missing_adjudications:
        raise ValueError(f"audit finding(s) missing an adjudication: {missing_adjudications}")
    duplicate_adjudications = sorted(
        {fid for fid in adjudication_id_list if adjudication_id_list.count(fid) > 1}
    )
    if duplicate_adjudications:
        raise ValueError(f"audit finding(s) with multiple adjudications: {duplicate_adjudications}")

    # Iterate adjudications in input order; this is also the order that
    # downstream rounds and operators see, and it is stable across processes
    # (unlike `set` iteration, which is hash-randomised in CPython by
    # default). The accepted/rejected lists therefore round-trip canonically.
    accepted_finding_ids: list[str] = [
        a["finding_id"] for a in payload["adjudications"] if a["verdict"] == "accept"
    ]

    # Every accepted finding MUST come with a Changelog entry and a SelfReview
    # entry (the author-round contract; see _shared/self-review.md). Schema
    # validation alone cannot enforce this — it spans three top-level arrays.
    # A schema-valid settle envelope that accepts a finding without recording
    # the corresponding edit and self-review would erode downstream trust:
    # Round 2a/3a would have no evidence to verify against.
    accepted_set = set(accepted_finding_ids)
    changelog_ids = {c["finding_id"] for c in payload["changelog"]}
    self_review_ids = {s["finding_id"] for s in payload["self_review"]}
    missing_changelog = sorted(accepted_set - changelog_ids)
    if missing_changelog:
        raise ValueError(f"accepted finding(s) missing a changelog entry: {missing_changelog}")
    missing_self_review = sorted(accepted_set - self_review_ids)
    if missing_self_review:
        raise ValueError(f"accepted finding(s) missing a self_review entry: {missing_self_review}")
    rejected_finding_ids: list[str] = [
        a["finding_id"] for a in payload["adjudications"] if a["verdict"] == "reject"
    ]
    accepted_findings = [audit_findings_by_id[fid] for fid in accepted_finding_ids]
    rejected_findings = []
    for fid in rejected_finding_ids:
        adj = next(a for a in payload["adjudications"] if a["finding_id"] == fid)
        rf = dict(audit_findings_by_id[fid])
        rf["rejection_reason"] = adj["reasoning"]
        rejected_findings.append(rf)
    envelope = {
        "round": round_num,
        "stage": stage,
        "schema_version": 1,
        "slug": slug,
        "artifact_type": artifact_type,
        "artifact_path": artifact_path,
        "emitted_at": now_iso8601_utc(),
        "slice_plan": paired_audit["slice_plan"],
        "adjudication_summary": {
            "accepted": len(accepted_finding_ids),
            "rejected": len(rejected_finding_ids),
        },
        "adjudications": payload["adjudications"],
        "accepted_findings": accepted_findings,
        "rejected_findings": rejected_findings,
        "changelog": payload["changelog"],
        "self_review": payload["self_review"],
    }
    if stage == "3b":
        envelope["final_status"] = (
            "READY_FOR_IMPLEMENTATION"
            if not accepted_findings
            else "CORRECTED_PENDING_VERIFICATION"
        )
    return envelope


def _build_verification_envelope(
    slug: str,
    artifact_type: str,
    artifact_path: str,
    payload: dict,
    paired_3b: dict,
    artifact_dir: Path,
    repo_root: Path,
) -> tuple[dict, str]:
    """Build a round-3c envelope. Returns (envelope, verified_content_hash).

    Raises ValueError on a 1:1 verification mismatch or a rerun-guard hit.
    """
    accepted = paired_3b["accepted_findings"]
    err = _check_verification_set(payload["verifications"], accepted)
    if err is not None:
        raise ValueError(err)

    verified_content_hash = compute_content_hash(repo_root / artifact_path)

    prior = _attempt_files(artifact_dir)
    if prior and prior[-1]["verified_content_hash"] == verified_content_hash:
        raise ValueError(
            f"3c rerun guard: the artifact is byte-identical to the last failed "
            f"verification attempt (attempt {prior[-1]['attempt_number']}, "
            f"{verified_content_hash}). Fix the artifact before rerunning final "
            f"verification."
        )
    attempt_number = (prior[-1]["attempt_number"] + 1) if prior else 1

    # Writer mints R3C-NNN ids in input order, overwriting any caller value.
    regressions = [dict(r) for r in payload["regression_findings"]]
    for idx, reg in enumerate(regressions, start=1):
        reg["id"] = f"R3C-{idx:03d}"

    result = (
        "passed"
        if all(v["status"] == "resolved" for v in payload["verifications"]) and not regressions
        else "failed"
    )
    envelope = {
        "round": 3,
        "stage": "3c",
        "schema_version": 1,
        "slug": slug,
        "artifact_type": artifact_type,
        "artifact_path": artifact_path,
        "emitted_at": now_iso8601_utc(),
        "attempt_number": attempt_number,
        "verified_content_hash": verified_content_hash,
        "verifications": payload["verifications"],
        "regression_findings": regressions,
        "result": result,
        "prior_attempts": [_prior_attempt_summary(a) for a in prior],
    }
    if result == "passed":
        envelope["final_status"] = "CORRECTED_AND_READY"
    return envelope, verified_content_hash


def _persist_verification(
    envelope: dict,
    verified_content_hash: str,
    artifact_dir: Path,
    state: dict,
    artifact_type: str,
    state_path: Path,
) -> None:
    """Write the 3c outcome. Pass -> round-3c.json + state update. Fail ->
    round-3c-attempt-NNN.json only (state.json untouched)."""
    body = canonical_json(envelope)
    if envelope["result"] == "passed":
        atomic_write(artifact_dir / "round-3c.json", body)
        block = state[artifact_type]
        block["completed_rounds"] = sorted({*block["completed_rounds"], "3c"})
        block["current_stage"] = "ready_for_implementation"
        block["last_updated_at"] = envelope["emitted_at"]
        block["content_hash"] = verified_content_hash
        state[artifact_type] = block
        atomic_write(state_path, canonical_json(state))
    else:
        n = envelope["attempt_number"]
        atomic_write(artifact_dir / f"round-3c-attempt-{n:03d}.json", body)
    sys.stdout.write(body)


def _cross_round_check_2a(envelope: dict, prior_settle_1b: dict) -> str | None:
    accepted_ids = {f["id"] for f in prior_settle_1b["accepted_findings"]}
    seen_ids: set[str] = set()
    for agent in envelope["agents"]:
        for v in agent["round_1_verifications"]:
            fid = v["round_1_finding_id"]
            if fid not in accepted_ids:
                return f"verification references unknown round-1 finding id {fid}"
            # Frozen-slice ownership: a finding's id format `R1-N-NNN` encodes
            # the originating agent_id (N). The verifying sub-agent in Round 2a
            # MUST be that same agent — otherwise an agent could verify another
            # slice's finding and the slice-isolation contract is broken.
            origin_agent = int(fid.split("-")[1])
            if origin_agent != agent["agent_id"]:
                return (
                    f"verification of {fid} reported by agent {agent['agent_id']}, "
                    f"expected agent {origin_agent} (frozen-slice ownership)"
                )
            seen_ids.add(fid)
    missing = accepted_ids - seen_ids
    if missing:
        return f"round_1_verifications missing entries for accepted findings: {sorted(missing)}"
    extra_count = sum(1 for a in envelope["agents"] for _ in a["round_1_verifications"]) - len(
        accepted_ids
    )
    if extra_count > 0:
        return f"round_1_verifications has {extra_count} more entries than accepted findings"
    return None


def _check_slice_plan_frozen(envelope: dict, prior_audit: dict) -> str | None:
    if envelope["slice_plan"] != prior_audit["slice_plan"]:
        return "slice_plan diverges from prior audit round (slice plan is frozen after Round 1a)"
    return None


def _read_optional(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def _auto_settle(
    audit_envelope: dict,
    state: dict,
    artifact_type: str,
    artifact_path: str,
    slug: str,
    artifact_dir: Path,
    state_path: Path,
    repo_root: Path,
) -> dict:
    """Generate, validate, and persist the no-op settle paired with a clean
    fast-mode audit. Reuses the manual-settle build/validate/persist path so
    auto-settle cannot bypass any check. Returns the settle envelope. Raises
    on any failure — the caller catches it and degrades to a manual settle.

    The audit round file and state.json have ALREADY been written by the
    caller before this runs; this function only ever advances state PAST the
    manual-settle boundary, never rolls the audit write back.
    """
    audit_stage = audit_envelope["stage"]
    settle_stage = {"1a": "1b", "2a": "2b"}[audit_stage]
    payload = {
        "stage": settle_stage,
        "adjudications": [],
        "changelog": [],
        "self_review": [],
    }
    envelope = _build_settle_envelope(
        slug, artifact_type, artifact_path, payload, audit_envelope, None
    )
    source_hash = compute_content_hash(artifact_dir / f"round-{audit_stage}.json")
    agent_count = len(audit_envelope["agents"])
    envelope["auto_settled"] = {
        "trigger": "clean_audit_zero_findings",
        "source_stage": audit_stage,
        "source_round_hash": source_hash,
        "reason": (
            f"Clean {audit_stage} audit: {agent_count} agents reported no "
            f"blocking findings; no-op settle auto-generated in fast mode."
        ),
    }
    schema = load_schema("round-settle.schema.json")
    Draft202012Validator(schema, registry=build_registry()).validate(envelope)
    body = canonical_json(envelope)
    # Compute the artifact hash up-front: it is the only other operation here
    # that can raise (e.g. the artifact file was moved/deleted), so doing it
    # before the round-file write ensures a hash failure cannot leave a
    # partial settle on disk.
    artifact_hash = compute_content_hash(repo_root / artifact_path)
    # Round file first: if this raises, state stays at the manual-settle
    # boundary and the caller reports AUTO_SETTLE_FAILED. After this point the
    # only operation that can fail is the state.json write itself.
    atomic_write(artifact_dir / f"round-{settle_stage}.json", body)
    block = state[artifact_type]
    block["completed_rounds"] = sorted({*block["completed_rounds"], settle_stage})
    block["current_stage"] = NEXT_STAGE[settle_stage]
    block["last_updated_at"] = envelope["emitted_at"]
    block["content_hash"] = artifact_hash
    state[artifact_type] = block
    atomic_write(state_path, canonical_json(state))
    return envelope


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument("--artifact-type", choices=["spec", "plan"], required=True)
    p.add_argument("--artifact-path", required=True)
    p.add_argument("--input", type=Path, required=True)
    args = p.parse_args()

    try:
        validate_slug(args.slug)
    except ValueError as e:
        return err(str(e))

    payload = json.loads(args.input.read_text())
    stage = payload.get("stage")
    if stage not in STAGE_TO_ROUND:
        return err(f"unknown stage: {stage!r}")

    repo_root = find_repo_root(Path.cwd())
    slug_dir = state_dir(repo_root) / args.slug
    artifact_dir = slug_dir / args.artifact_type
    state_path = slug_dir / "state.json"
    if not state_path.exists():
        return err(f"no state.json for slug {args.slug!r}; run cr_state_init first")
    state = json.loads(state_path.read_text())
    # Schema validation guards against hand-edited or otherwise corrupted
    # state.json: without this, the writer would mutate schema-violating
    # state and persist invalid bytes back, propagating the corruption
    # forward. The both-block invariant below catches one specific
    # cross-block case the schema cannot express; this validation catches
    # the broader class. Read paths in `cr_state_read.py` deliberately do
    # NOT validate — refusing to read corrupted state would prevent
    # recovery. The check belongs at write entry only.
    state_schema = load_schema("state.schema.json")
    state_registry = build_registry()
    try:
        Draft202012Validator(state_schema, registry=state_registry).validate(state)
    except jsonschema.ValidationError as e:
        path = "/" + "/".join(str(p) for p in e.absolute_path)
        return err(f"state.json schema violation: {e.message} at {path}")
    # Both-block invariant: if state has both spec and plan blocks, the plan
    # block MUST carry `spec_hash_at_start`. The state.schema.json cannot
    # express this conditional requirement, and `_cmd_check_spec_drift` in
    # `cr_state_read.py` treats a missing anchor as non-drift — so a state
    # that violates the invariant silently disables spec-drift protection.
    # We re-enforce it at every write entry rather than trusting the init
    # path alone, because a corrupted local state or a bootstrap paste that
    # bypassed the same check elsewhere must surface here before any further
    # round envelope is emitted.
    if "spec" in state and "plan" in state and "spec_hash_at_start" not in state.get("plan", {}):
        return err(
            "state integrity: state.json has both 'spec' and 'plan' blocks "
            "but state.plan.spec_hash_at_start is missing (would silently "
            "bypass spec-drift detection). Re-run cr_state_init for the "
            "plan block, or re-import a corrected state.json."
        )
    block = state.get(args.artifact_type)
    if block is None:
        return err(f"state.json has no {args.artifact_type!r} block; run cr_state_init")

    expected_stage = block["current_stage"].replace("round_", "").replace("_pending", "")
    if expected_stage != stage:
        return err(f"state expects stage {expected_stage!r} next; got {stage!r}")

    # Identity check: --artifact-path MUST match what state.json captured at
    # init time. Without this, a local write can silently produce a round
    # envelope referencing a different path than the canonical one in state,
    # which would then be rejected by `cr_state_read.py --paste` on the
    # destination host (§10.3 identity contract). Failing fast here keeps the
    # diagnostic local instead of surfacing only after a cross-host paste.
    if args.artifact_path != block["path"]:
        return err(
            f"--artifact-path {args.artifact_path!r} does not match the path captured in "
            f"state.json for {args.artifact_type!r} block ({block['path']!r}). "
            f"Re-run with --artifact-path {block['path']}."
        )

    artifact_dir.mkdir(parents=True, exist_ok=True)

    if stage in VERIFY_STAGES:
        paired_3b = _read_optional(artifact_dir / "round-3b.json")
        if paired_3b is None:
            return err("3c requires round-3b.json (the accepted-blocker source) on disk")
        try:
            envelope, verified_hash = _build_verification_envelope(
                args.slug,
                args.artifact_type,
                args.artifact_path,
                payload,
                paired_3b,
                artifact_dir,
                repo_root,
            )
        except ValueError as e:
            return err(str(e))
        schema = load_schema("final-verification.schema.json")
        try:
            Draft202012Validator(schema, registry=build_registry()).validate(envelope)
        except jsonschema.ValidationError as e:
            path = "/".join(str(p) for p in e.absolute_path) or "<root>"
            return err(f"schema violation at {path}: {e.message}")
        _persist_verification(
            envelope,
            verified_hash,
            artifact_dir,
            state,
            args.artifact_type,
            state_path,
        )
        return 0

    paired_audit_path = {"1b": "1a", "2b": "2a", "3b": "3a"}.get(stage)
    prior_settle_path = {"2a": "1b", "3a": "2b"}.get(stage)
    prior_audit_path = {"2a": "1a", "3a": "2a"}.get(stage)

    paired_audit = (
        _read_optional(artifact_dir / f"round-{paired_audit_path}.json")
        if paired_audit_path
        else None
    )
    prior_settle = (
        _read_optional(artifact_dir / f"round-{prior_settle_path}.json")
        if prior_settle_path
        else None
    )
    prior_audit = (
        _read_optional(artifact_dir / f"round-{prior_audit_path}.json")
        if prior_audit_path
        else None
    )

    try:
        if stage in AUDIT_STAGES:
            envelope = _build_audit_envelope(
                args.slug, args.artifact_type, args.artifact_path, payload, prior_audit
            )
        else:
            if paired_audit is None:
                return err(f"settle stage {stage} requires the paired audit file")
            envelope = _build_settle_envelope(
                args.slug,
                args.artifact_type,
                args.artifact_path,
                payload,
                paired_audit,
                prior_settle,
            )
    except ValueError as e:
        return err(str(e))

    schema_name = "round-audit.schema.json" if stage in AUDIT_STAGES else "round-settle.schema.json"
    schema = load_schema(schema_name)
    registry = build_registry()
    try:
        Draft202012Validator(schema, registry=registry).validate(envelope)
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "<root>"
        return err(f"schema violation at {path}: {e.message}")

    # Cross-round invariants
    if stage == "2a":
        if prior_settle is None:
            return err(
                "round 2a requires round-1b.json (the prior round-1b settle "
                "file, source of the accepted findings 2a verifies) on disk"
            )
        msg = _cross_round_check_2a(envelope, prior_settle)
        if msg:
            return err(msg)
    if stage in {"2a", "3a"} and prior_audit is not None:
        msg = _check_slice_plan_frozen(envelope, prior_audit)
        if msg:
            return err(msg)

    body = canonical_json(envelope)
    atomic_write(artifact_dir / f"round-{stage}.json", body)

    block["completed_rounds"] = sorted({*block["completed_rounds"], stage})
    if stage == "3a" and _is_clean_3a(envelope):
        block["current_stage"] = "ready_for_implementation"
    elif stage == "3b" and envelope["final_status"] == "CORRECTED_PENDING_VERIFICATION":
        block["current_stage"] = "round_3c_pending"
    else:
        block["current_stage"] = NEXT_STAGE[stage]
    block["last_updated_at"] = envelope["emitted_at"]
    # Settle rounds (1b/2b/3b) edit the artifact in place (per the round
    # markdown procedures). Refresh `block.content_hash` to the post-edit
    # bytes so any later plan-init under the same slug captures the
    # *approved* spec hash, not the pre-review hash. Without this, a normal
    # spec→plan handoff would anchor `state.plan.spec_hash_at_start` to
    # stale spec bytes and the very first plan drift check (Phase 6) would
    # report drift on every successful spec review. Audit rounds (1a/2a/3a)
    # do not edit the artifact, so their content_hash stays stable.
    if stage in SETTLE_STAGES:
        block["content_hash"] = compute_content_hash(repo_root / args.artifact_path)
    state[args.artifact_type] = block
    atomic_write(state_path, canonical_json(state))

    # Auto-settle: in fast mode a clean 1a/2a audit gets its no-op settle
    # generated in-process. Eligibility is decided here, never by the router.
    if stage in {"1a", "2a"} and block.get("mode") == "fast":
        is_clean = _is_clean_1a(envelope) if stage == "1a" else _is_clean_2a(envelope)
        if is_clean:
            try:
                settle_env = _auto_settle(
                    envelope,
                    state,
                    args.artifact_type,
                    args.artifact_path,
                    args.slug,
                    artifact_dir,
                    state_path,
                    repo_root,
                )
            except Exception as exc:  # degrade to manual settle
                # Failure isolation: the audit write above is committed and
                # valid; state stays at the manual-settle boundary. Emit an
                # explicit structured marker so the round procedure can tell
                # this apart from an ordinary manual-settle path.
                print(f"AUTO_SETTLE_FAILED: {exc}", file=sys.stderr)
                sys.stdout.write(body)
                return 0
            sys.stdout.write(canonical_json({"written_rounds": [envelope, settle_env]}))
            return 0

    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
