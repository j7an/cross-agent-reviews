# Round 2a — Reviewer audit (verification round)

Use when `state.<artifact_type>.current_stage == "round_2a_pending"`. Fresh-session preflight is REQUIRED.

## 1. Read the canonical slice plan and Round 1b output

Read `.cross-agent-reviews/<slug>/<artifact_type>/round-1a.json` for the frozen slice plan and `round-1b.json` for the accepted findings (each accepted finding's `agent_id` indicates which slice must verify it).

## 2. Reuse the slice plan exactly

Do NOT redefine the slice plan and do NOT include `slice_plan` in the payload below. `cr_state_write.py` sources `slice_plan` from `round-1a.json` (the prior audit) for stages `2a` and `3a` and ignores any `slice_plan` field on the input payload; it then enforces equality between the envelope's `slice_plan` and Round 1a's. The cross-artifact slice (agent_id 6, is_fixed: true) is preserved if it was present.

## 3. Pre-extraction step (cross-artifact slice only)

If the cross-artifact slice is present and the artifact is the plan, re-run `"${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr" extract-placeholders --spec-path <SPEC> --plan-path <PLAN>` against the corrected plan. The agent_id 6 sub-agent receives the new extractor report.

## 4. Dispatch with verification mission

Apply the dispatch template with:

- `${ROUND} = 2`, `${STAGE} = "2a"`
- `${ROUND_MISSION_TEXT}` =
  > For each accepted Round 1 finding assigned to your slice, verify
  > whether the author's edit resolved it (status: `resolved` |
  > `partially_resolved` | `not_resolved`) and quote the corrected
  > excerpt as `evidence`. Then re-read your slice for any NEW findings
  > the corrections introduced. Allowed severities for new findings:
  > `blocker` (implementer cannot proceed) or `gap` (material omission).
  > Do not nit-pick at this stage. Per-slice sub-agent status MUST be
  > `verified` (every assigned Round 1 finding resolved AND zero new
  > findings) or `issues_found` (≥1 unresolved Round 1 finding OR ≥1
  > new finding).
- `${PRIOR_ROUND_FINDINGS_JSON}` = the subset of `accepted_findings` from Round 1b whose `id` matches `R1-<slice agent_id>-NNN`.

## 5. Aggregate and write

Build:

```json
{
  "stage": "2a",
  "agents": [
    {
      "agent_id": 1, "concern": "...", "slice_definition": "...",
      "status": "verified | issues_found",
      "findings": [],
      "round_1_verifications": [
        {"round_1_finding_id": "R1-1-001", "status": "resolved", "evidence": "..."}
      ]
    }
  ]
}
```

The agents array MUST contain one verification per accepted Round 1 finding (cardinality enforced by `cr_state_write.py`). Then:

```bash
"${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr" state-write --slug <slug> --artifact-type <type> --artifact-path <path> --input <tmp-payload.json>
```
