# Sub-agent dispatch template

Use this template when spawning each sub-agent for a Round Na audit. The
parameters `${ROUND}` and `${STAGE}` and `${ROUND_MISSION_TEXT}` are filled
in by the round-procedure file (e.g., `rounds/1a-audit.md`) before
dispatch — the LLM never assembles raw envelope JSON; that is the script's
job.

## Required parameters

- `${ROUND}` — integer 1, 2, or 3
- `${STAGE}` — string "1a", "2a", or "3a"
- `${SLICE_AGENT_ID}` — integer 1-6
- `${SLICE_CONCERN}` — short concern label
- `${SLICE_DEFINITION}` — exact sections/lines this sub-agent reviews
- `${ARTIFACT_PATH}` — path to the spec or plan
- `${ARTIFACT_TYPE}` — "spec" or "plan"
- `${ROUND_MISSION_TEXT}` — round-specific mission paragraph (different
  language for 1a, 2a, 3a; supplied by the round-procedure file)
- `${PRIOR_ROUND_FINDINGS_JSON}` — for 2a only; the accepted Round 1
  findings as a JSON array (one entry per finding the sub-agent must
  verify); empty `[]` for 1a and 3a

## Sub-agent prompt template

```text
You are sub-agent ${SLICE_AGENT_ID} for Round ${STAGE} of the cross-agent
review pipeline. Your concern is: ${SLICE_CONCERN}. Your slice is:
${SLICE_DEFINITION}.

${ROUND_MISSION_TEXT}

The artifact to review is at: ${ARTIFACT_PATH} (${ARTIFACT_TYPE}).

For Round 2a only: verify each accepted Round 1 finding listed below was
resolved by the author's edits, and emit one verification per finding.
${PRIOR_ROUND_FINDINGS_JSON}

Return a status report following the protocol in
[../_shared/status-protocol.md](../_shared/status-protocol.md). The
protocol's emission discipline and recoverable statuses
(`blocked` / `needs_context`) always apply; the per-stage success/failure
status enum (`findings_found` / `clean` for 1a, `verified` / `issues_found`
for 2a, `ship_ready` / `blocker_found` for 3a) is the one supplied in
${ROUND_MISSION_TEXT} above and overrides the protocol's success/failure
labels for stages 2a and 3a. The status report you return is consumed by
the round procedure (which calls `cr_state_write.py` to assemble
the canonical envelope). You do NOT emit the round envelope JSON yourself
— only your per-slice findings, verifications, and status.
```

## Cross-artifact slice override (plan reviews only)

When the round is on a plan AND `state.spec.path` is non-null, the slice
plan has 6 entries (5 internal + 1 fixed cross-artifact). For
`SLICE_AGENT_ID == 6`, the round procedure invokes
`cr_extract_placeholders.py` first and supplies its JSON output as
the sub-agent's primary input via the
[`cross-artifact-slice.md`](cross-artifact-slice.md) addendum. See that
file for the full per-classification rubric.
