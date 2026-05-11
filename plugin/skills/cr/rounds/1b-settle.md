# Round 1b — Author settle

Use when `state.<artifact_type>.current_stage == "round_1b_pending"`. Fresh-session preflight is NOT required.

## 1. Read the round-1a output

`"${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr" state-read --slug <slug> --artifact-type <type>` (use the local file). The 1a findings are at `.cross-agent-reviews/<slug>/<artifact_type>/round-1a.json` under `agents[].findings`.

## 2. Adjudicate every finding

For each finding, decide accept or reject. Capture:

- Adjudication record `{finding_id, verdict, reasoning}`.
- For `accept`: edit the artifact in place to address the finding (minimum-correction principle), and add a Changelog entry `{finding_id, change_made}` describing the actual edit.
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

## 4. Write

```bash
"${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr" state-write --slug <slug> --artifact-type <type> --artifact-path <path> --input <tmp-payload.json>
```

The script computes `accepted_findings`, `rejected_findings`,
`adjudication_summary`, and persists `round-1b.json`. State advances to
`round_2a_pending`.
