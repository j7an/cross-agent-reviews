---
name: cr-3b-final-settle
description: Round 3b (author, terminal) — final adjudication and ship verdict. Use when the operator pastes Round 3 verification JSON. Applies the strictest filter (accept only literal blockers), edits the artifact in place if any blockers were accepted, self-reviews each correction, and emits the final status READY_FOR_IMPLEMENTATION or CORRECTED_AND_READY. Pipeline terminates. Fresh session.
---

<!-- Architecture adapted from superpowers:dispatching-parallel-agents and superpowers:subagent-driven-development v5.0.7. Full attribution: ../_shared/attribution.md -->

[Full attribution](../_shared/attribution.md)

## 0. Pre-flight: confirm fresh session

Follow the procedure documented in [../_shared/preflight.md](../_shared/preflight.md) before doing any work.

## 1. When to use

Use after Round 3a. The operator pastes the Round 3 verification JSON. This is the terminal round — no next-skill handoff. The artifact ships after this round regardless of outstanding non-blocker findings.

## 2. Extract context from input JSON

The operator will paste the full Round 3 verification JSON. Extract:
- `artifact_type` (`spec` or `plan`) — copy unchanged into output
- `artifact_path` (string) — copy unchanged into output; validate it resolves to an existing file BEFORE applying any edits
- `slice_plan` (array) — copy unchanged into output
- per-slice `agents[].blockers` arrays — the blocker findings to adjudicate

Stage discriminator (§7.6): the input MUST contain an `agents` array (with per-slice `blockers` arrays) and MUST have `round == 3`. If the discriminator does not match, halt with `NEEDS_CONTEXT` status and ask the operator to repaste the correct round's JSON.

This round does NOT prompt the operator for an artifact path — the path travels with the JSON paste from Round 3a. Do NOT request a Round 1a JSON or any earlier-round JSON.

If `artifact_path` does not resolve to a readable file, halt with `BLOCKED` status before applying any edits and ask the operator to confirm or supply a corrected path. See spec §7.1 path/type correction exception.

## 3. Adjudicate findings (strictest filter)

Apply the strictest filter. Accept only findings describing something an implementer literally cannot proceed without. Reject everything else with one-line reasoning.

After this round, the artifact ships regardless of outstanding non-blocker findings.

## 4. Apply accepted edits to artifact in place (transition rule)

If accepted > 0: edit the {spec|plan} artifact in place at `artifact_path` with minimum corrections. Set `final_status` to `CORRECTED_AND_READY`.

If accepted = 0: leave the artifact unchanged. Set `final_status` to `READY_FOR_IMPLEMENTATION`.

Do not rewrite for style, expand scope, or over-specify.

## 5. Author session model tier guidance

Use the most capable model available for this session. Final-round adjudication is the highest-stakes judgment in the pipeline — the marginal cost of a stronger model is paid back in fewer mis-rejections and tighter corrections.

## 6. Self-review checklist

After applying each accepted correction and before emitting JSON, run the checklist in [../_shared/self-review.md](../_shared/self-review.md). Fix anything flagged before output.

## 7. Status report

Use the status format in [../_shared/status-report.md](../_shared/status-report.md): `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT`.

## 8. Output JSON schema

Enums: final_status = READY_FOR_IMPLEMENTATION|CORRECTED_AND_READY; verdict = accept|reject.

Always copy `artifact_type`, `artifact_path`, and `slice_plan` unchanged from the Round 3 verification JSON.
Always include every array shown in the schema. Use `[]` when empty.

Return ONLY this JSON in your reply (the artifact, if updated, lives in the edited file):

```json
{
  "round": 3,
  "artifact_type": "spec",
  "artifact_path": "docs/specs/foo.md",
  "slice_plan": [
    {
      "agent_id": 1,
      "concern": "Data model & schemas",
      "slice_definition": "sections/lines reviewed"
    }
  ],
  "final_status": "READY_FOR_IMPLEMENTATION",
  "adjudication_summary": {"accepted": 0, "rejected": 0},
  "adjudications": [
    {
      "finding_id": "R3-1-001",
      "verdict": "accept",
      "reasoning": "one sentence"
    }
  ],
  "changelog": [
    {
      "finding_id": "R3-1-001",
      "change_made": "one sentence"
    }
  ],
  "self_review": [
    {
      "finding_id": "R3-1-001",
      "resolved": true,
      "over_specified": false,
      "introduces_contradiction": false,
      "notes": "only if flagged"
    }
  ]
}
```

Round 3 verification JSON:
---
{round_3_verification_json}
