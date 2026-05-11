# Round 2b — Author settle (post-verification adjudication)

Use when `state.<artifact_type>.current_stage == "round_2b_pending"`. Fresh-session preflight is NOT required.

## 1. Read Round 2a verifications and new findings

`.cross-agent-reviews/<slug>/<artifact_type>/round-2a.json` contains:

- `agents[].round_1_verifications[]` — verification of every Round 1b accepted finding.
- `agents[].findings[]` — any NEW findings raised in Round 2a.

## 2. Triage verifications

For each `round_1_verifications` entry whose `status != "resolved"`, decide whether to revisit the prior change. The verification is informational; you do not adjudicate it (no `Adjudication` record). If you choose to revisit, edit the artifact and capture an additional `ChangelogEntry` with the original Round 1 `finding_id` (e.g., `R1-5-001`); also capture a `SelfReviewEntry` under the same id so the revisit is held to the same fix-before-emit standard as adjudicated edits. `cr_state_write.py` accepts these `R1-*` ids in 2b changelog and self_review arrays by sourcing them from the paired 2a's `round_1_verifications` (the paired audit's NEW findings remain the only valid ids for `Adjudication` records).

## 3. Adjudicate the NEW findings only

Only the `findings` array of Round 2a's agents enters the adjudication. For each new finding:

- Build an `Adjudication` `{finding_id, verdict: accept | reject, reasoning}`.
- For accept: edit the artifact in place; add a `ChangelogEntry`.
- For reject: justify in `rejection_reason`.
- Add a `SelfReviewEntry`.

## 4. Build the payload

```json
{
  "stage": "2b",
  "adjudications": [...],
  "rejected_findings": [],
  "changelog": [...],
  "self_review": [...]
}
```

`cr_state_write.py` joins the adjudications with Round 2a's `findings` to compute `accepted_findings` and `rejected_findings`.

## 5. Write

```bash
"${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr" state-write --slug <slug> --artifact-type <type> --artifact-path <path> --input <tmp-payload.json>
```
