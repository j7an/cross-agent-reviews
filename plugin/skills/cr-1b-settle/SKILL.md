---
name: cr-1b-settle
description: Round 1b (author) — adjudicate Round 1a findings and edit the artifact. Use when the operator pastes Round 1a JSON. Validates the stage discriminator, accepts or rejects each finding, applies accepted edits to the artifact in place with minimum corrections, self-reviews each correction, and emits Round 1 adjudication JSON consumed by `cr-2a-audit` in a separate session. Fresh session.
---

<!-- Architecture adapted from superpowers:dispatching-parallel-agents and superpowers:subagent-driven-development v5.0.7. Full attribution: ../_shared/attribution.md -->

[Full attribution](../_shared/attribution.md)

## 0. Pre-flight: confirm fresh session

Follow the procedure documented in [../_shared/preflight.md](../_shared/preflight.md) before doing any work.

## 1. When to use

Use this skill after Round 1a has produced its JSON output. The operator will paste the Round 1a JSON; this skill consumes it, edits the artifact, and produces JSON for the next round.

## 2. Extract context from input JSON

The operator will paste the full Round 1a JSON. Extract:
- `artifact_type` (`spec` or `plan`) — copy unchanged into output
- `artifact_path` (string) — copy unchanged into output; validate it resolves to an existing file BEFORE applying any edits
- `slice_plan` (array) — copy unchanged into output
- `agents[].findings` — the per-slice findings to adjudicate

Stage discriminator (§7.6): the input MUST contain an `agents` array, MUST NOT contain `accepted_findings`, and MUST have `round == 1`. If the discriminator does not match, halt with `NEEDS_CONTEXT` status and ask the operator to repaste the correct round's JSON.

If `artifact_path` does not resolve to a readable file, halt with `BLOCKED` status before applying any edits and ask the operator to confirm or supply a corrected path. See spec §7.1 path/type correction exception.

## 3. Adjudicate findings

Adjudicate each finding: accept | reject.
- Reject all `nit` findings unless they create genuine ambiguity
- Reject `false_positive_check` findings unless you independently confirm them
- Reject findings that misread intentional abstraction as imprecision
- Defending correct decisions is part of your job; do not capitulate

## 4. Apply accepted edits to artifact in place

Edit the {spec|plan} artifact in place at `artifact_path`, applying only accepted findings with minimum changes. Do not rewrite for style, expand scope, or over-specify.

## 5. Author session model tier guidance

Use the most capable model available for this session. Adjudication is judgment work — the marginal cost of a stronger model is paid back in fewer mis-rejections and tighter corrections.

## 6. Self-review checklist

After applying each accepted correction and before emitting JSON, run the checklist in [../_shared/self-review.md](../_shared/self-review.md). Fix anything flagged before output.

## 7. Status report

Use the status format in [../_shared/status-report.md](../_shared/status-report.md): `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`.

## 8. Output JSON schema

Enums: verdict = accept|reject; severity = blocker|gap|nit|false_positive_check.

Always copy `artifact_type`, `artifact_path`, and `slice_plan` unchanged from the Round 1 review JSON.
Always include every array shown in the schema. Use `[]` when empty.

Return ONLY this JSON in your reply (the corrected artifact lives in the edited file, not here):

```json
{
  "round": 1,
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
      "finding_id": "R1-1-001",
      "verdict": "accept",
      "reasoning": "one sentence"
    }
  ],
  "accepted_findings": [
    {
      "id": "R1-1-001",
      "location": "section/line reference",
      "severity": "gap",
      "finding": "one sentence",
      "why_it_matters": "one sentence",
      "suggested_direction": "one sentence"
    }
  ],
  "rejected_findings": [
    {
      "id": "R1-1-002",
      "location": "section/line reference",
      "severity": "nit",
      "finding": "one sentence",
      "why_it_matters": "one sentence",
      "suggested_direction": "one sentence",
      "rejection_reason": "one sentence"
    }
  ],
  "changelog": [
    {
      "finding_id": "R1-1-001",
      "change_made": "one sentence describing the actual edit"
    }
  ],
  "self_review": [
    {
      "finding_id": "R1-1-001",
      "resolved": true,
      "over_specified": false,
      "introduces_contradiction": false,
      "notes": "only if any concern flagged"
    }
  ]
}
```

Paste the full Round 1 review JSON below.
---
{round_1_review_json}
