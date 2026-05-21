# Round 1b — Author settle

Use when `state.<artifact_type>.current_stage == "round_1b_pending"`. Fresh-session preflight is NOT required.

## Helper setup

Before any shell tool call in this round that invokes a helper, define
`CR_HELPER` in that same shell tool call:

```bash
CR_HELPER="<absolute path to the loaded cr skill directory>/_helpers/cr"
```

## 1. Read the round-1a output

Run:

```bash
CR_HELPER="<absolute path to the loaded cr skill directory>/_helpers/cr"
"${CR_HELPER}" state-read --slug <slug> --artifact-type <type>
```

Use the local file. The 1a findings are at `.cross-agent-reviews/<slug>/<artifact_type>/round-1a.json` under `agents[].findings`.

## 2. Adjudicate every finding

For each finding, decide accept or reject. Capture:

- Adjudication record `{finding_id, verdict, reasoning}`.
- For `accept`: edit the artifact in place to address the finding (minimum-correction principle), and add a Changelog entry `{finding_id, change_made, additional_affected_slices}` describing the actual edit. `additional_affected_slices` is an array of integer agent_ids for cross-slice edits; explicit empty `[]` is allowed and is treated as "no cross-slice impact". Absence triggers fallback reason `F2-2`.
- For `accept`: additionally capture two strings on the adjudication record
  in fast / profile-aware mode:
  - `fix_criterion`: the criterion by which the fix should be judged.
  - `verification_target`: the artifact location the verifier should re-read.
  These fields are optional in legacy / thorough mode; their absence in fast
  mode triggers fallback reason `F2-1` on the next route decision.
- For `reject`: justify in `rejection_reason`.
- Add a self-review entry `{finding_id, resolved, over_specified, introduces_contradiction, notes}`.

## 3. Build the payload

```json
{
  "stage": "1b",
  "adjudications": [...],
  "rejected_findings": [],
  "changelog": [...],
  "self_review": [...]
}
```

> Note: `rejected_findings` is built by `cr_state_write.py` from
> `adjudications[verdict == "reject"]` joined with the matching audit
> findings; you supply only the empty `[]` here. If you want to attach
> richer rejection reasoning, the script copies it from the adjudication.

> The writer derives `finding_lineage` from your adjudications + changelog
> when the artifact block is in **fast / profile-aware mode**
> (`mode == 'fast'` AND `review_profile` set). You do not author this field
> directly. In thorough mode, or in a fast block whose profile is unset,
> `finding_lineage` is omitted entirely.

## 4. Write

```bash
CR_HELPER="<absolute path to the loaded cr skill directory>/_helpers/cr"
"${CR_HELPER}" state-write --slug <slug> --artifact-type <type> --artifact-path <path> --input <tmp-payload.json>
```

The script computes `accepted_findings`, `rejected_findings`,
`adjudication_summary`, and persists `round-1b.json`. State advances to
`round_2a_pending`.
