---
name: cr-2b-settle
description: Round 2b (author) — adjudicate Round 2a verification and edit the artifact. Use when the operator pastes both the Round 1 adjudication JSON (for canonical slice_plan) and the Round 2 verification JSON. Validates both stage discriminators, accepts or rejects each issue, applies accepted edits with minimum corrections, self-reviews, and emits Round 2 adjudication JSON consumed by `cr-3a-final-audit`. Fresh session.
---

<!-- Architecture adapted from superpowers:dispatching-parallel-agents and superpowers:subagent-driven-development v5.0.7. Full attribution: ../_shared/attribution.md -->

[Full attribution](../_shared/attribution.md)

## 0. Pre-flight: confirm fresh session

Follow the procedure documented in [../_shared/preflight.md](../_shared/preflight.md) before doing any work.

## 1. When to use

Use this skill after Round 2a has produced its verification JSON. The operator will paste TWO JSON blocks (the Round 1 adjudication JSON and the Round 2 verification JSON); this skill consumes both, edits the artifact, and produces JSON for the next round.

## 2. Extract context from input JSON

The operator will paste two blocks: the Round 1 adjudication JSON, then the Round 2 verification JSON. Validate stage discriminators on BOTH before extracting:

- Round 1 adjudication JSON discriminator (§7.6): the block MUST contain both `accepted_findings` AND `rejected_findings` arrays and MUST have `round == 1`.
- Round 2 verification JSON discriminator (§7.6): the block MUST contain an `agents` array (with per-slice `round_1_verifications` and `new_findings`) and MUST have `round == 2`.

If either signature does not match, halt with `NEEDS_CONTEXT` status and ask the operator to repaste the correct round's JSON.

From the Round 1 adjudication JSON, extract (and copy unchanged into output):
- `artifact_type` (`spec` or `plan`)
- `artifact_path` (string) — validate it resolves to an existing file BEFORE applying any edits
- `slice_plan` (array) — canonical per-round freeze
- `accepted_findings` — the canonical original-finding list (used to identify which Round 1 findings were re-flagged this round)
- `rejected_findings` — propagated unchanged

From the Round 2 verification JSON, consume:
- per-slice `round_1_verifications` — resolution status of each Round 1 accepted finding
- per-slice `new_findings` — Round 2 blockers/gaps introduced by the corrections

If `artifact_path` does not resolve to a readable file, halt with `BLOCKED` status before applying any edits and ask the operator to confirm or supply a corrected path. See spec §7.1 path/type correction exception.

## 3. Adjudicate findings

Adjudicate each verification issue: accept | reject.
- Accept only unresolved Round 1 findings or genuinely new blockers/gaps
- For `partially_resolved` or `not_resolved` verification items: accept and re-correct, or reject if the verifier misread the correction
- Round 2 should accept far fewer findings than Round 1
- If you find yourself accepting more than 2 new findings, stop and check whether you are capitulating instead of defending
- Reject by default

Id rule: re-accepted Round 1 findings keep their original `R1-N-NNN` id; new Round 2 findings use `R2-N-NNN`.

## 4. Apply accepted edits to artifact in place

Edit the {spec|plan} artifact in place at `artifact_path`, applying only accepted findings with minimum changes. Do not rewrite for style, expand scope, or over-specify.

## 5. Author session model tier guidance

Use the most capable model available for this session. Adjudication is judgment work — the marginal cost of a stronger model is paid back in fewer mis-rejections and tighter corrections.

## 6. Self-review checklist

After applying each accepted correction and before emitting JSON, run the checklist in [../_shared/self-review.md](../_shared/self-review.md). Fix anything flagged before output.

## 7. Status report

Use the status format in [../_shared/status-report.md](../_shared/status-report.md): `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`.

## 8. Output JSON schema

Enums: verdict = accept|reject; severity = blocker|gap.

Always copy `artifact_type`, `artifact_path`, and `slice_plan` unchanged from the Round 1 adjudication JSON.
Always include every array shown in the schema. Use `[]` when empty.

Return ONLY this JSON in your reply (the corrected artifact lives in the edited file, not here):

```json
{
  "round": 2,
  "artifact_type": "spec",
  "artifact_path": "docs/specs/foo.md",
  "slice_plan": [
    {
      "agent_id": 1,
      "concern": "Data model & schemas",
      "slice_definition": "sections/lines reviewed"
    }
  ],
  "adjudication_summary": {"accepted": 0, "rejected": 0},
  "adjudications": [
    {
      "finding_id": "R2-1-001",
      "verdict": "accept",
      "reasoning": "one sentence"
    }
  ],
  "accepted_findings": [
    {
      "id": "R2-1-001",
      "location": "section/line",
      "severity": "blocker",
      "finding": "one sentence",
      "why_it_matters": "one sentence",
      "suggested_direction": "one sentence"
    }
  ],
  "rejected_findings": [
    {
      "id": "R2-1-002",
      "location": "section/line",
      "severity": "gap",
      "finding": "one sentence",
      "why_it_matters": "one sentence",
      "suggested_direction": "one sentence",
      "rejection_reason": "one sentence"
    }
  ],
  "changelog": [
    {
      "finding_id": "R2-1-001",
      "change_made": "one sentence"
    }
  ],
  "self_review": [
    {
      "finding_id": "R2-1-001",
      "resolved": true,
      "over_specified": false,
      "introduces_contradiction": false,
      "notes": "only if flagged"
    }
  ]
}
```

Round 1 adjudication JSON (for original accepted findings and `slice_plan`):
---
{round_1_adjudication_json}

Round 2 verification JSON:
---
{round_2_verification_json}
