#!/usr/bin/env python3
"""Render a human-readable timeline view of state across slugs."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from _cr_lib import find_repo_root, state_dir, terminal_shape, validate_slug
from cr_routing import decide_2a, decide_3a, identify_mandatory_slices

ROUND_STAGES = ("1a", "1b", "2a", "2b", "3a", "3b", "3c")


def _humanize_age(then_iso: str, now: datetime) -> str:
    then = datetime.strptime(then_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    diff = now - then
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h{m}m ago"
    return f"{seconds // 86400}d ago"


def _render_block(art: str, block: dict, artifact_dir: Path, now: datetime) -> list[str]:
    lines = [f"  {art.capitalize():<5} ({block['path']})"]
    mode = block.get("mode")
    mode_label = mode if mode is not None else "thorough (default)"
    profile = block.get("review_profile")
    profile_label = profile if profile is not None else "(legacy — unset)"
    lines.append(f"    Mode: {mode_label}   Profile: {profile_label}")
    completed = set(block["completed_rounds"])
    current = block["current_stage"]
    shape = terminal_shape(block["completed_rounds"])
    is_clean_3a_terminal = current == "ready_for_implementation" and shape == "clean_3a"
    is_via_3b_terminal = current == "ready_for_implementation" and shape == "via_3b"
    attempts = sorted(artifact_dir.glob("round-3c-attempt-*.json")) if artifact_dir.exists() else []
    route_lines: dict[str, str] = {}
    if block.get("mode") == "fast":
        r1a = _read_round(artifact_dir, "1a")
        r1b = _read_round(artifact_dir, "1b")
        if r1a is not None and r1b is not None:
            # Defensive: malformed slice_plan / round files shouldn't crash
            # the status renderer. Skip the route line on failure; the rest
            # of the block still renders.
            with contextlib.suppress(ValueError, KeyError):
                route_lines["2a"] = _format_route_line(
                    decide_2a(block, r1a, r1b), r1a, r1b, None, None, "2a"
                )
        r2a = _read_round(artifact_dir, "2a")
        r2b = _read_round(artifact_dir, "2b")
        if r1a is not None and r1b is not None and r2a is not None and r2b is not None:
            with contextlib.suppress(ValueError, KeyError):
                route_lines["3a"] = _format_route_line(
                    decide_3a(block, r1a, r1b, r2a, r2b), r1a, r1b, r2a, r2b, "3a"
                )
    for stage in ROUND_STAGES:
        if stage == "3b" and is_clean_3a_terminal:
            # 3b is neither completed nor pending for a clean-3a terminal;
            # render it explicitly so it is not confused with "not reached".
            # Gated on the terminal stage too: a round_3b_pending state shares
            # the clean_3a completed_rounds set ({1a,1b,2a,2b,3a}) but has NOT
            # terminated, so it must still render "PENDING", not "skipped".
            lines.append(f"    {stage:<3}  skipped (clean 3a)")
        elif stage == "3c" and is_clean_3a_terminal:
            lines.append(f"    {stage:<3}  skipped (clean 3a)")
        elif stage == "3c" and is_via_3b_terminal:
            lines.append(f"    {stage:<3}  skipped (3b accepted zero findings)")
        elif stage in completed:
            rp = artifact_dir / f"round-{stage}.json"
            if rp.exists():
                round_data = json.loads(rp.read_text())
                emitted = round_data["emitted_at"]
                auto = round_data.get("auto_settled")
                suffix = route_lines.get(stage, "")
                if auto is not None:
                    src = auto["source_stage"]
                    lines.append(
                        f"    {stage:<3}  completed (auto-settled from clean "
                        f"{src}){suffix}  {emitted}   ({_humanize_age(emitted, now)})"
                    )
                else:
                    lines.append(
                        f"    {stage:<3}  completed{suffix}  {emitted}   ({_humanize_age(emitted, now)})"
                    )
            else:
                lines.append(f"    {stage:<3}  completed  (round file missing — pending import)")
        elif stage == "3c" and current == "round_3c_pending":
            if attempts:
                lines.append(
                    f"    {stage:<3}  FAILED  (final verification — "
                    f"{len(attempts)} failed attempt(s))"
                )
            else:
                lines.append(f"    {stage:<3}  PENDING  (final verification)")
        elif current == f"round_{stage}_pending":
            suffix = route_lines.get(stage, "")
            lines.append(f"    {stage:<3}  PENDING{suffix}")
        else:
            lines.append(f"    {stage:<3}  —")
    if current == "ready_for_implementation":
        # Suppress the terminal summary whenever ANY completed round file is
        # missing locally — not just the last one. The read/router path
        # (`cr_state_read.py::_classify`) treats any completed-but-missing
        # stage as a pending import, so a "READY_FOR_IMPLEMENTATION" /
        # final_status summary would contradict it while the per-stage loop
        # above already flags the gap. Name the earliest-missing stage in
        # canonical pipeline order, matching the pending-import scan.
        missing = next(
            (
                s
                for s in ROUND_STAGES
                if s in completed and not (artifact_dir / f"round-{s}.json").exists()
            ),
            None,
        )
        if missing is not None:
            lines.append(f"  Terminal:  (round-{missing}.json pending import)")
        elif shape == "clean_3a":
            lines.append("  Terminal:  READY_FOR_IMPLEMENTATION  (clean 3a - round 3b skipped)")
        elif shape == "via_3b":
            rb = artifact_dir / "round-3b.json"
            cpv = False
            if rb.exists():
                with contextlib.suppress(json.JSONDecodeError):
                    cpv = (
                        json.loads(rb.read_text()).get("final_status")
                        == "CORRECTED_PENDING_VERIFICATION"
                    )
            if not cpv:
                lines.append(
                    "  Terminal:  READY_FOR_IMPLEMENTATION  (via round 3b - zero accepted)"
                )
            # cpv==True: no Terminal line — _integrity_for surfaces the error instead
        elif shape == "via_3c":
            final_status = json.loads((artifact_dir / "round-3c.json").read_text())["final_status"]
            lines.append(f"  Terminal:  {final_status}  (via round 3c - final verification passed)")
        # shape == "invalid": no Terminal line — _integrity_for surfaces the
        # integrity error instead of an inferred final_status.
    elif current == "round_3c_pending":
        if attempts:
            latest = json.loads(attempts[-1].read_text())
            unresolved = sum(1 for v in latest["verifications"] if v["status"] == "not_resolved")
            regressions = len(latest["regression_findings"])
            lines.append(
                f"  Final verification:  FAILED  (attempt {latest['attempt_number']} - "
                f"{unresolved} blocker(s) unresolved, {regressions} regression(s); "
                f"fix the artifact and run /cr)"
            )
        else:
            lines.append("  Final verification:  PENDING  (run /cr to dispatch round 3c)")
    return lines


def _integrity_for(state: dict, slug_dir: Path) -> str:
    for art in ("spec", "plan"):
        block = state.get(art)
        if block is None:
            continue
        if (
            block["current_stage"] == "ready_for_implementation"
            and terminal_shape(block["completed_rounds"]) == "invalid"
        ):
            return "STATE_INTEGRITY_ERROR"
        artifact_dir = slug_dir / art
        if (
            block["current_stage"] == "ready_for_implementation"
            and terminal_shape(block["completed_rounds"]) == "via_3b"
        ):
            rb = artifact_dir / "round-3b.json"
            if rb.exists():
                try:
                    r3b = json.loads(rb.read_text())
                except json.JSONDecodeError:
                    r3b = None
                if r3b is not None and r3b.get("final_status") == "CORRECTED_PENDING_VERIFICATION":
                    return "STATE_INTEGRITY_ERROR"
        max_emitted = ""
        for stage in block["completed_rounds"]:
            rp = artifact_dir / f"round-{stage}.json"
            if not rp.exists():
                continue
            emitted = json.loads(rp.read_text())["emitted_at"]
            if emitted > max_emitted:
                max_emitted = emitted
        if max_emitted and block["last_updated_at"] < max_emitted:
            return "STATE_INTEGRITY_ERROR"
    return "OK"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--slug")
    args = p.parse_args()
    if args.slug is not None:
        try:
            validate_slug(args.slug)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    repo_root = find_repo_root(Path.cwd())
    state_root = state_dir(repo_root)
    if not state_root.exists():
        print("No active slugs.")
        return 0
    slugs = sorted(state_root.iterdir()) if args.slug is None else [state_root / args.slug]
    now = datetime.now(UTC)
    for slug_dir in slugs:
        sp = slug_dir / "state.json"
        if not sp.is_file():
            continue
        state = json.loads(sp.read_text())
        print(f"Slug: {state['slug']}")
        for art in ("spec", "plan"):
            block = state.get(art)
            if block is None:
                print(f"  {art.capitalize():<5} [not yet started]")
                continue
            for line in _render_block(art, block, slug_dir / art, now):
                print(line)
        print()
        print(
            f"State integrity:  {_integrity_for(state, slug_dir)}  (state.json ↔ round emitted_at)"
        )
        print()
    return 0


def _read_round(artifact_dir: Path, stage: str) -> dict | None:
    p = artifact_dir / f"round-{stage}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def _format_route_line(decision, r1a, r1b, r2a, r2b, stage: str) -> str:
    """Format the suffix appended after PENDING/completed for fast-mode blocks.

    Broad lines name the highest-priority fallback reason (lowest sort key)
    with a compact one-clause expansion so an operator does not have to run
    --verbose to know why.
    """
    if decision.scope == "narrow":
        mandatory = identify_mandatory_slices(r1a["slice_plan"])
        m = mandatory["global_coherence_slice"]
        return (
            f"  (narrow: slices {', '.join(str(s) for s in decision.selected_slices)}; "
            f"mandatory: {m})"
        )
    first = sorted(decision.fallback_reasons)[0]
    slice_plan = r1a["slice_plan"]
    if stage == "2a":
        expansion = _compact_reason_2a(first, r1b, slice_plan)
    else:
        expansion = _compact_reason_3a(first, r1b, r2a, r2b, slice_plan)
    return f"  (broad: fallback — {expansion})"


def _compact_reason_2a(code: str, r1b: dict, slice_plan: list[dict]) -> str:
    """Compact one-clause expansion for status output. Names the offending
    finding_id for the state-dependent codes (F2-1..F2-3); returns a static
    label for the stateless codes (F2-4..F2-7).

    Note F2-4 is reachable from status output: a `mode == "fast"` block with
    no `review_profile` still renders a route line (spec §9 gates only on
    mode, not on the profile), and the route decision returns broad with
    F2-4. The static map handles it directly."""
    static = {
        "F2-4": "F2-4 review_profile unset (legacy)",
        "F2-5": "F2-5 review_profile is greenfield",
        "F2-6": "F2-6 mode is not fast",
        "F2-7": "F2-7 mandatory slice undetectable",
    }
    if code in static:
        return static[code]
    accepted_ids = {f["id"] for f in r1b.get("accepted_findings", [])}
    valid = {s["agent_id"] for s in slice_plan}
    if code == "F2-1":
        for adj in r1b.get("adjudications", []):
            if adj.get("verdict") == "accept" and (
                not adj.get("fix_criterion") or not adj.get("verification_target")
            ):
                missing = []
                if not adj.get("fix_criterion"):
                    missing.append("fix_criterion")
                if not adj.get("verification_target"):
                    missing.append("verification_target")
                return f"F2-1 missing {'+'.join(missing)} on {adj['finding_id']}"
    if code == "F2-2":
        for entry in r1b.get("changelog", []):
            if entry["finding_id"] in accepted_ids and "additional_affected_slices" not in entry:
                return (
                    f"F2-2 changelog for {entry['finding_id']} missing additional_affected_slices"
                )
    if code == "F2-3":
        for entry in r1b.get("changelog", []):
            if entry["finding_id"] not in accepted_ids:
                continue
            bad = [a for a in entry.get("additional_affected_slices", []) if a not in valid]
            if bad:
                return f"F2-3 {entry['finding_id']} declares unknown slice(s) {bad}"
    return code


def _compact_reason_3a(code, r1b, r2a, r2b, slice_plan):
    if code == "F3-1":
        # F3-1 collapses F2-1 / F2-2 / F2-3 against the 2b envelope plus the
        # mandatory-slice failure. Re-probe each in order and re-label the
        # first that fires; if none fire (defensive), fall through to a
        # generic message.
        if not slice_plan or all(s.get("is_fixed") for s in slice_plan):
            return "F3-1 mandatory slice undetectable"
        for inner in ("F2-1", "F2-2", "F2-3"):
            expanded = _compact_reason_2a(inner, r2b, slice_plan)
            if expanded != inner:
                tail = expanded[len(inner) + 1 :]  # strip "F2-X " (NOTE: space, not colon)
                return f"F3-1 via {inner} {tail}"
        return "F3-1 2b lineage author fields incomplete"
    if code == "F3-2":
        return "F3-2 3a impact routing requires fast + patch"
    if code == "F3-3":
        for agent in r2a.get("agents", []):
            for v in agent.get("round_1_verifications", []):
                if v.get("status") in {"not_resolved", "partially_resolved"}:
                    return f"F3-3 {v['round_1_finding_id']} verified as {v['status']}"
    if code == "F3-4":
        for f in r2b.get("accepted_findings", []):
            if f.get("severity") == "blocker":
                return f"F3-4 accepted 2a blocker {f['id']}"
    if code == "F3-5":
        return "F3-5 lineage carry-forward incomplete"
    return code


if __name__ == "__main__":
    sys.exit(main())
