# Round 1a — Reviewer audit (entry into the pipeline)

Use this procedure when `state.<artifact_type>.current_stage == "round_1a_pending"`. Fresh-session preflight already passed (the router checked).

## 1. Capture artifact context

The router has already determined `slug`, `artifact_path`, and
`artifact_type`. They live in `state.<artifact_type>` under the slug's
`state.json`.

## 2. Define the slice plan

Review the artifact using 5 parallel sub-agents.

If artifact_type is `spec`:
1. Data model & schemas
2. Error handling & edge cases
3. Acceptance criteria & testability
4. Cross-section consistency
5. Global coherence (does it solve the stated problem?)

If artifact_type is `plan`:
- Agents 1-4: one per major phase/component (decide split based on plan
  structure; if fewer than 4 phases, combine related sections; if more,
  group adjacent ones).
- Agent 5: cross-cutting (dependency ordering, phase handoffs, sequencing
  risks).

If artifact_type is `plan` AND `state.spec.path` is non-null, append a
6th fixed slice: cross-artifact integrity. See
[../_shared/cross-artifact-slice.md](../_shared/cross-artifact-slice.md).
Set `is_fixed: true` for this slot. The slice plan is otherwise
**frozen** for rounds 2a and 3a — Round 2a/3a re-uses this exact split.

For each slice, capture: `agent_id`, `concern`, `slice_definition` (exact
sections/lines/grouped phases), `is_fixed` (false for slices 1-5; true
for the cross-artifact slice when present).

## 3. Pre-extraction step (cross-artifact slice only)

If a 6th cross-artifact slice is present, run:

```bash
uv run python scripts/cr_extract_placeholders.py --spec-path <SPEC> --plan-path <PLAN>
```

Capture the JSON output. The agent_id 6 sub-agent receives this as primary
input alongside the rubric in
[../_shared/cross-artifact-slice.md](../_shared/cross-artifact-slice.md).

## 4. Model tier and dispatch

Apply [_shared/model-tier-rubric.md](../_shared/model-tier-rubric.md) for
per-slice model selection. Dispatch in parallel using
[_shared/dispatch-template.md](../_shared/dispatch-template.md), with:

- `${ROUND} = 1`, `${STAGE} = "1a"`
- `${ROUND_MISSION_TEXT}` =
  > Identify findings in your assigned slice. Possible severities:
  > `blocker` (implementer cannot proceed without resolution), `gap`
  > (material omission), `nit` (style / clarity), `false_positive_check`
  > (low-confidence apparent issue that may turn out to be a false alarm
  > on closer reading — flag it so the author can confirm or dismiss
  > rather than silently suppressing your doubt). Round 1a has no prior
  > rounds, so the prior-round-verification meaning of
  > `false_positive_check` from rounds 2a/3a does NOT apply here. Return
  > your findings using the structured shape; the script assigns IDs.
- `${PRIOR_ROUND_FINDINGS_JSON}` = `[]` (Round 1a has no prior findings)

If a sub-agent returns escalation status (`blocked`, `needs_context`),
halt the round before invoking `cr_state_write.py`. Surface the
escalation, address it (correct slice definition or supply context), and
re-dispatch the affected slice.

## 5. Aggregate and write

Collect each sub-agent's status report. Build a JSON payload:

```json
{
  "stage": "1a",
  "slice_plan": [...],
  "agents": [
    {"agent_id": 1, "concern": "...", "slice_definition": "...", "status": "findings_found|clean", "findings": [...]}
  ]
}
```

Save the payload to a temp file and run:

```bash
uv run python scripts/cr_state_write.py --slug <slug> --artifact-type <type> --artifact-path <path> --input <tmp-payload.json>
```

The script validates, writes `round-1a.json` to disk, updates
`state.json`, and emits byte-identical JSON to stdout. The router then
emits the round-completion message.
