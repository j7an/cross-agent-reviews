# Round 2b — Author settle (post-verification adjudication)

Use when `state.<artifact_type>.current_stage == "round_2b_pending"`. Fresh-session preflight is NOT required.

## Helper setup

Before any shell tool call in this round that invokes a helper, define
`CR_HELPER` in that same shell tool call:

```bash
CR_HELPER="<absolute path to the loaded cr skill directory>/_helpers/cr"
```

## 1. Read Round 2a verifications and new findings

`.cross-agent-reviews/<slug>/<artifact_type>/round-2a.json` contains:

- `agents[].round_1_verifications[]` — verification of every Round 1b accepted finding.
- `agents[].findings[]` — any NEW findings raised in Round 2a.

## 2. Triage verifications

For each `round_1_verifications` entry whose `status != "resolved"`, decide whether to revisit the prior change. The verification is informational; you do not adjudicate it (no `Adjudication` record). If you choose to revisit, edit the artifact and capture an additional `ChangelogEntry` with the original Round 1 `finding_id` (e.g., `R1-5-001`); also capture a `SelfReviewEntry` under the same id so the revisit is held to the same fix-before-emit standard as adjudicated edits. `cr_state_write.py` accepts these `R1-*` ids in 2b changelog and self_review arrays by sourcing them from the paired 2a's `round_1_verifications` (the paired audit's NEW findings remain the only valid ids for `Adjudication` records).

## 3. Adjudicate the NEW findings only

Only the `findings` array of Round 2a's agents enters the adjudication. For each new finding:

- Build an `Adjudication` `{finding_id, verdict: accept | reject, reasoning}`.
- For accept: edit the artifact in place; add a `ChangelogEntry`
  `{finding_id, change_made, additional_affected_slices}`.
  `additional_affected_slices` is an array of integer agent_ids for
  cross-slice edits; explicit empty `[]` is allowed and is treated as
  "no cross-slice impact". Absence triggers fallback reason `F3-1` (via
  the 2b-side replay of F2-2) on the next 3a route decision.
- For accept: additionally capture two strings on the adjudication record
  in fast / profile-aware mode:
  - `fix_criterion`: the criterion by which the fix should be judged.
  - `verification_target`: the artifact location the verifier should re-read.
  These fields are optional in legacy / thorough mode; their absence in fast
  mode triggers fallback reason `F3-1` (via the 2b-side replay of F2-1) on
  the next 3a route decision. The `--verbose` reader surfaces the inner
  cause as `F3-1 via F2-1: ...` so operators can see which specific 2b
  adjudication is incomplete.
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

> The writer derives `finding_lineage` from your Round 2 adjudications +
> changelog when the artifact block is in **fast / profile-aware mode**
> (`mode == 'fast'` AND `review_profile` set). You do not author this field
> directly. In thorough mode, or in a fast block whose profile is unset,
> `finding_lineage` is omitted entirely.

## 5. Write

```bash
CR_HELPER="<absolute path to the loaded cr skill directory>/_helpers/cr"
"${CR_HELPER}" state-write --slug <slug> --artifact-type <type> --artifact-path <path> --input <tmp-payload.json>
```
