---
name: cr-3a-final-audit
description: Round 3a (reviewer, strict) — final blocker check before ship. Use when the operator pastes Round 2 adjudication JSON. Freezes the slice plan, dispatches 5 parallel sub-agents to look strictly for true blockers (an implementer literally cannot proceed without resolution), aggregates per-slice ship_ready or blocker_found verdicts, and emits Round 3 verification JSON consumed by `cr-3b-final-settle`. Fresh session.
---

<!-- Architecture adapted from superpowers:dispatching-parallel-agents and superpowers:subagent-driven-development v5.0.7. Full attribution: ../_shared/attribution.md -->

[Full attribution](../_shared/attribution.md)

## 0. Pre-flight: confirm fresh session

Follow the procedure documented in [../_shared/preflight.md](../_shared/preflight.md) before doing any work.

## 1. When to use

Use this skill after Round 2b has produced its adjudication JSON. The operator will paste the Round 2 adjudication JSON; this skill performs the strict final-check pass and produces JSON for the terminal round.

## 2. Extract context from input JSON

The operator will paste the full Round 2 adjudication JSON. Extract:
- `artifact_type` (`spec` or `plan`) — copy unchanged into output
- `artifact_path` (string) — copy unchanged into output; validate it resolves to an existing file BEFORE dispatching sub-agents
- `slice_plan` (array) — copy unchanged into output; freeze (do not modify)
- `accepted_findings` — already addressed by Round 2b; informational only at this round
- `rejected_findings` — sub-agents MUST NOT reopen these

Stage discriminator (§7.6): the input MUST contain both `accepted_findings` AND `rejected_findings` arrays and MUST have `round == 2`. If the discriminator does not match, halt with `needs_context` status and ask the operator to repaste the correct round's JSON.

If `artifact_path` does not resolve to a readable file, halt with `blocked` status and ask the operator to confirm or supply a corrected path. See spec §7.1 path/type correction exception.

This round does NOT prompt the operator for an artifact path — the path travels with the JSON paste from Round 2b.

## 3. Reuse the slice plan (strict final check)

Final verification of the corrected {spec|plan}. 5 parallel sub-agents, same split as previous rounds.

Use the provided `slice_plan` exactly as given. Do not change agent boundaries, labels, or slice definitions.

Strict — only blockers an implementer literally cannot proceed without. Default to ship_ready. The bar is high. Do NOT check for resolution of prior-round findings — that's 2a's job.

Each sub-agent looks for ONE thing only in its slice: blockers. A blocker means the artifact cannot be implemented as written without further clarification.

Do not flag gaps, nits, style issues, or anything in `rejected_findings`.

## 4. Model tier guidance

Apply the tier rubric in [../_shared/model-tier-rubric.md](../_shared/model-tier-rubric.md) when choosing per-slice models for sub-agent dispatch. Round 3a is the final ship gate; default to the most capable available model unless a slice is unambiguously well-bounded.

## 5. Per-slice sub-agent dispatch

Use the dispatch template in [../_shared/dispatch-template-3a.md](../_shared/dispatch-template-3a.md) when spawning each sub-agent. One sub-agent per slice; dispatch in parallel.

## 6. Status protocol & aggregation

Aggregate sub-agent results per [../_shared/status-protocol.md](../_shared/status-protocol.md). Recover from `blocked` / `needs_context` before emitting round-level JSON.

### Round 3a Aggregation Override

The dispatch template `dispatch-template-3a.md` instructs sub-agents to report using the inherited 1a vocabulary (`findings_found` / `clean` per-slice plus a generic `findings` array). For Round 3a, sub-agents MUST surface ONLY blocker-severity items (drop `gap`, `nit`, `false_positive_check`). When aggregating into the round-level output, map each sub-agent report:

- A per-slice `findings_found` report with at least one blocker-severity item → round-level slice status `blocker_found`, with the blocker items copied into the slice's `blockers` array (rewriting per-finding fields to the 3a shape: `id`, `location`, `blocker`, `why_unimplementable`).
- A per-slice `clean` report — or a `findings_found` report whose only items were dropped because they were not blocker severity — → round-level slice status `ship_ready` and an empty `blockers: []` array.

The dispatch template's generic `findings` array is dropped entirely at aggregation time; Round 3a emits only `blockers` per slice.

## 7. Output JSON schema + emit rules

Enums: artifact_type = spec|plan; status = ship_ready|blocker_found.

Always copy `artifact_type`, `artifact_path`, and `slice_plan` unchanged from the Round 2 adjudication JSON.
Always include every array shown in the schema. Use `[]` when empty.

Output ONLY this JSON in your reply (use one concrete enum value per field, not the alternation):

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
  "agents": [
    {
      "agent_id": 1,
      "concern": "Data model & schemas",
      "slice_definition": "sections/lines reviewed",
      "status": "ship_ready",
      "blockers": [
        {
          "id": "R3-1-001",
          "location": "section/line",
          "blocker": "one sentence",
          "why_unimplementable": "one sentence - be specific about what an implementer cannot do"
        }
      ]
    }
  ]
}
```

Round 2 adjudication JSON (use `accepted_findings`, `rejected_findings`, and `slice_plan`):
---
{round_2_adjudication_json}
