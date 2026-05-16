# Round 3c — Final verification (conditional, terminal-on-pass)

Use when `state.<artifact_type>.current_stage == "round_3c_pending"`. This
stage runs **only** when Round 3b accepted ≥1 finding (`final_status:
CORRECTED_PENDING_VERIFICATION`). Fresh-session preflight **is** required — `3c`
must not be run by the Round 3b author's session.

## 1. Fresh-session preflight

Execute [_shared/preflight.md](../_shared/preflight.md) before anything else,
exactly as the audit rounds do. `3c` independently verifies the 3b author's
corrections; a carried-over session defeats that.

## 2. Read the inputs

- `.cross-agent-reviews/<slug>/<artifact_type>/round-3b.json` — its
  `accepted_findings` is the exact set of 3a blockers to verify; its
  `changelog` and `self_review` record what the 3b author claims they did.
- The current artifact at `state.<artifact_type>.path`.

## 3. Verify each accepted blocker

For **every** finding in `round-3b.json` `accepted_findings`, inspect the
artifact and decide:

- `resolved` — the blocker is genuinely fixed in the current artifact bytes.
- `not_resolved` — the blocker remains, or the edit does not actually address it.

Record concrete `evidence` citing the artifact location. Scope is strict:
verify *that blocker*, nothing else. Do not re-audit.

## 4. Regression sweep

Scan the regions the 3b edits touched (per `round-3b.json` `changelog`) for
**obvious new blockers** the corrections introduced — a broken cross-reference,
a contradiction, a dangling definition. Record each as a regression finding.
Only blocker-severity regressions count; do not log nits or speculative gaps.

## 5. Build the payload

```json
{
  "stage": "3c",
  "verifications": [
    {"round_3a_finding_id": "R3-<agent>-<nnn>", "status": "resolved|not_resolved", "evidence": "..."}
  ],
  "regression_findings": [
    {"location": "...", "severity": "blocker", "finding": "...", "why_it_matters": "...", "suggested_direction": "..."}
  ]
}
```

Provide exactly one `verifications` entry per accepted blocker. Omit `id` on
regression findings — the writer mints `R3C-NNN`.

## 6. Write

```bash
"${CLAUDE_PLUGIN_ROOT}/skills/cr/_helpers/cr" state-write --slug <slug> --artifact-type <type> --artifact-path <path> --input <tmp-payload.json>
```

The writer derives `result`:

- **passed** (every verification `resolved`, zero regressions) → writes
  `round-3c.json` with `final_status: CORRECTED_AND_READY`, completes the
  pipeline.
- **failed** → appends `round-3c-attempt-NNN.json` and leaves state at
  `round_3c_pending`. Fix the artifact, then run `/cr` to re-verify. The writer
  refuses a rerun if the artifact is byte-identical to the last failed attempt.

The router emits the terminal or `BLOCKED:final-verification` message per
`SKILL.md` §5.
