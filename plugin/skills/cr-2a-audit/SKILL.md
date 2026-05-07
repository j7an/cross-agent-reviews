---
name: cr-2a-audit
description: Round 2a (reviewer) — verify Round 1b corrections. Use when the operator pastes Round 1b adjudication JSON. Freezes the slice plan, dispatches 5 parallel sub-agents to confirm accepted findings were resolved and that corrections did not introduce new blockers, aggregates per-slice results, and emits Round 2 verification JSON consumed by `cr-2b-settle` in a separate session. Fresh session.
---

<!-- Architecture adapted from superpowers:dispatching-parallel-agents and superpowers:subagent-driven-development v5.0.7. Full attribution: ../_shared/attribution.md -->

[Full attribution](../_shared/attribution.md)

## 0. Pre-flight: confirm fresh session

Follow the procedure documented in [../_shared/preflight.md](../_shared/preflight.md) before doing any work.

## 1. When to use

Use this skill after Round 1b has produced its adjudication JSON. The operator will paste the Round 1b JSON; this skill verifies the corrections, dispatches sub-agents, and produces JSON for the next round.

## 2. Extract context from input JSON

The operator will paste the full Round 1b adjudication JSON. Extract:
- `artifact_type` (`spec` or `plan`) — copy unchanged into output
- `artifact_path` (string) — copy unchanged into output; validate it resolves to an existing file BEFORE dispatching sub-agents
- `slice_plan` (array) — copy unchanged into output; freeze (do not modify)
- `accepted_findings` (array) — distribute to sub-agents per slice for resolution-verification
- `rejected_findings` (array) — copy unchanged into output; sub-agents MUST NOT reopen these

Stage discriminator (§7.6): the input MUST contain an `accepted_findings` array and MUST have `round == 1`. If the discriminator does not match, halt with `needs_context` status and ask the operator to repaste the correct round's JSON.

If `artifact_path` does not resolve to a readable file, halt with `blocked` status and ask the operator to confirm or supply a corrected path. See spec §7.1 path/type correction exception.

## 3. Reuse the slice plan

Verify the corrected {spec|plan} using 5 parallel sub-agents.

Use the provided `slice_plan` exactly as given. Do not change agent boundaries, labels, or slice definitions.

Each sub-agent verifies ONLY two things in its assigned slice:
1. Were Round 1 accepted findings in this slice actually resolved?
2. Did corrections introduce NEW blockers or gaps in this slice?

Do not flag nits. Do not reopen or restate anything in `rejected_findings`.

Sub-agents return verified status if everything resolved and no new blockers/gaps were introduced.

## 4. Model tier guidance

Apply the tier rubric in [../_shared/model-tier-rubric.md](../_shared/model-tier-rubric.md) when choosing per-slice models for sub-agent dispatch.

## 5. Per-slice sub-agent dispatch

Use the dispatch template in [../_shared/dispatch-template-2a.md](../_shared/dispatch-template-2a.md) when spawning each sub-agent. One sub-agent per slice; dispatch in parallel.

## 6. Status protocol & aggregation

Aggregate sub-agent results per [../_shared/status-protocol.md](../_shared/status-protocol.md). Recover from `blocked` / `needs_context` before emitting round-level JSON.

### Round 2a Report-Format Override

The dispatch template inherited from `dispatch-template-2a.md` instructs sub-agents to report using the generic 1a vocabulary (`findings_found` / `clean` per-slice plus a generic `findings` array). For Round 2a, this report format is SUPERSEDED. Each sub-agent MUST instead:

- Return per-slice status `verified` (all assigned `accepted_findings` resolved AND no new blockers/gaps) or `issues_found` (otherwise) — replacing the inherited `findings_found` / `clean` enum.
- Emit a `round_1_verifications` array — one entry per assigned accepted finding — with fields `round_1_finding_id`, `status` (one of `resolved` | `partially_resolved` | `not_resolved`), and a one-sentence `evidence` string quoting the corrected artifact.
- Emit a `new_findings` array (same per-finding fields as Round 1a: `id`, `location`, `severity`, `finding`, `why_it_matters`, `suggested_direction`) for genuinely new blockers or gaps introduced by the corrections. Sub-agents MUST drop nits and false-positive-checks at this round.
- Drop the inherited generic `findings` array entirely; Round 2a sub-agents emit `round_1_verifications` and `new_findings` only.

## 7. Output JSON schema + emit rules

Enums: artifact_type = spec|plan; agents.status = verified|issues_found; round_1_verifications.status = resolved|partially_resolved|not_resolved; severity = blocker|gap.

Round-level top-level `status` is `verified` only if every slice reports `verified`; otherwise `issues_found`.

Always copy `artifact_type`, `artifact_path`, and `slice_plan` unchanged from the Round 1 adjudication JSON.
Always include every array shown in the schema. Use `[]` when empty.

Output ONLY this JSON in your reply (use one concrete enum value per field, not the alternation):

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
  "agents": [
    {
      "agent_id": 1,
      "concern": "Data model & schemas",
      "slice_definition": "sections/lines reviewed",
      "status": "verified",
      "round_1_verifications": [
        {
          "round_1_finding_id": "R1-1-001",
          "status": "resolved",
          "evidence": "quoted excerpt from corrected artifact"
        }
      ],
      "new_findings": [
        {
          "id": "R2-1-001",
          "location": "section/line",
          "severity": "blocker",
          "finding": "one sentence",
          "why_it_matters": "one sentence",
          "suggested_direction": "one sentence"
        }
      ]
    }
  ]
}
```

Round 1 adjudication JSON (use `accepted_findings`, `rejected_findings`, and `slice_plan`):
---
{round_1_adjudication_json}
