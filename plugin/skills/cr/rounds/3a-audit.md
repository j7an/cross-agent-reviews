# Round 3a — Final reviewer audit (strict pass)

Use when `state.<artifact_type>.current_stage == "round_3a_pending"`. Fresh-session preflight is REQUIRED.

## 1. Reuse the canonical slice plan

Same as Round 2a; do NOT include `slice_plan` in the payload below — `cr_state_write.py` sources it from `round-1a.json` and enforces equality.

## 2. Pre-extraction step (cross-artifact slice only)

If the cross-artifact slice is present and the artifact is the plan, re-run `uv run python scripts/cr_extract_placeholders.py --spec-path <SPEC> --plan-path <PLAN>` once more against the now-final plan.

## 3. Dispatch with strict-blocker mission

Apply the dispatch template with:

- `${ROUND} = 3`, `${STAGE} = "3a"`
- `${ROUND_MISSION_TEXT}` =
  > Look strictly for true blockers — issues an implementer literally
  > cannot proceed without resolution. Allowed severity: `blocker` only.
  > No gaps, no nits, no false_positive_check. Sub-agent status MUST be
  > `ship_ready` (zero findings) or `blocker_found` (≥1 blocker).
- `${PRIOR_ROUND_FINDINGS_JSON}` = `[]` (3a does not re-verify; that was 2a's job).

## 4. Aggregate and write

Build:

```json
{
  "stage": "3a",
  "agents": [
    {
      "agent_id": 1, "concern": "...", "slice_definition": "...",
      "status": "ship_ready | blocker_found",
      "findings": [],
      "round_1_verifications": []
    }
  ]
}
```

Then:

```bash
uv run python scripts/cr_state_write.py --slug <slug> --artifact-type <type> --artifact-path <path> --input <tmp-payload.json>
```
