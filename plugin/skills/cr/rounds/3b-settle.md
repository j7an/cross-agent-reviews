# Round 3b — Final author settle (terminal)

Use when `state.<artifact_type>.current_stage == "round_3b_pending"`. Fresh-session preflight is NOT required.

## 1. Read Round 3a findings

`.cross-agent-reviews/<slug>/<artifact_type>/round-3a.json` lists any final blockers.

## 2. Apply the strictest filter

For each Round 3a finding, decide accept or reject. Accept ONLY a finding that is a literal blocker (an implementer cannot proceed without it). For accepted findings, edit the artifact and add a `ChangelogEntry` + `SelfReviewEntry`.

## 3. Build the payload

```json
{
  "stage": "3b",
  "adjudications": [...],
  "rejected_findings": [],
  "changelog": [...],
  "self_review": [...]
}
```

## 4. Write — `final_status` is auto-derived

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr_state_write.py" --slug <slug> --artifact-type <type> --artifact-path <path> --input <tmp-payload.json>
```

The script derives `final_status` from `len(accepted_findings)`:

- 0 → `READY_FOR_IMPLEMENTATION` (artifact ships unchanged).
- ≥1 → `CORRECTED_AND_READY` (artifact edited; ships with corrections).

The router emits the terminal completion message based on `final_status`.
