---
name: cr-1a-audit
description: Round 1a (reviewer) — entry point of the 3-round / 6-step cross-agent spec/plan review pipeline. Use when the operator supplies a spec or plan path to start review. Defines a slice plan, dispatches 5 parallel sub-agents (one per slice), aggregates findings, and emits Round 1 JSON consumed by `cr-1b-settle` in a separate session. Fresh session, ideally on a different host than the artifact author.
---

<!-- Architecture adapted from superpowers:dispatching-parallel-agents and superpowers:subagent-driven-development v5.0.7. Full attribution: ../_shared/attribution.md -->

[Full attribution](../_shared/attribution.md)

## 0. Pre-flight: confirm fresh session

Follow the procedure documented in [../_shared/preflight.md](../_shared/preflight.md) before doing any work.

## 1. When to use

Use this skill at the start of a cross-agent review pipeline, after the operator has finished writing a spec or plan and saved it to a known path. This is the ONLY round that does not consume pasted JSON from a previous round — the operator supplies the artifact path directly. All subsequent rounds (1b → 2a → 2b → 3a → 3b) consume the previous round's JSON output via paste.

## 2. Capture artifact context

Extract two values from the operator's request:

- `artifact_path` — captured verbatim from the operator's message (no normalization). The operator MAY supply absolute or relative paths; the skill propagates the captured string unchanged through every subsequent round. Operators using different hosts per round should supply absolute paths.
- `artifact_type` — one of `spec` or `plan`. Inferred from the operator's request, the artifact's filename (`*-design.md` → spec, `*-plan.md` → plan), or the artifact's content if needed. If ambiguous, ask the operator before proceeding.

If `artifact_path` does not resolve to a readable file in the current working directory, halt with `blocked` status and ask the operator to confirm or supply a corrected path. See spec §7.1 path correction exception.

## 3. Define the slice plan

Review the attached {spec|plan} using 5 parallel sub-agents.

If artifact is a spec, split sub-agents by concern:
1. Data model & schemas
2. Error handling & edge cases
3. Acceptance criteria & testability
4. Cross-section consistency
5. Global coherence (does it solve the stated problem?)

If artifact is a plan, split sub-agents by structure:
- Agents 1-4: one per major phase/component (decide the split based on plan structure; if fewer than 4 phases exist, combine related sections; if more, group adjacent ones)
- Agent 5: cross-cutting (dependency ordering, phase handoffs, sequencing risks)

When you choose the split, define it explicitly in top-level `slice_plan`. For each agent include:
- `agent_id`
- `concern`
- `slice_definition`: exact sections, lines, or grouped phases assigned to that agent

Later rounds will reuse this split exactly, so make every `slice_definition` concrete enough to reproduce.

Each sub-agent reviews ONLY its assigned slice. Sub-agents must not invent issues; return clean status if nothing is found in that slice.

## 4. Model tier guidance

Apply the tier rubric in [../_shared/model-tier-rubric.md](../_shared/model-tier-rubric.md) when choosing per-slice models for sub-agent dispatch.

## 5. Per-slice sub-agent dispatch

Use the dispatch template in [../_shared/dispatch-template-1a.md](../_shared/dispatch-template-1a.md) when spawning each sub-agent. One sub-agent per slice; dispatch in parallel.

## 6. Status protocol & aggregation

Aggregate sub-agent results per [../_shared/status-protocol.md](../_shared/status-protocol.md). Recover from `blocked` / `needs_context` before emitting round-level JSON.

## 7. Output JSON schema + emit rules

Severity definitions:
- blocker: artifact cannot be implemented as written
- gap: information needed for implementation is missing
- nit: style, precision, or clarity improvement only
- false_positive_check: looks like an issue but <70% confidence

Enums: artifact_type = spec|plan; status = findings_found|clean|blocked|needs_context; severity = blocker|gap|nit|false_positive_check.

Always include every array shown in the schema. Use `[]` when empty.

Output ONLY this JSON in your reply (use one concrete enum value per field, not the alternation):

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
  "agents": [
    {
      "agent_id": 1,
      "concern": "Data model & schemas",
      "slice_definition": "sections/lines reviewed",
      "status": "findings_found",
      "findings": [
        {
          "id": "R1-1-001",
          "location": "section/line reference",
          "severity": "gap",
          "finding": "one sentence",
          "why_it_matters": "one sentence",
          "suggested_direction": "one sentence - direction only, not prescriptive wording"
        }
      ]
    }
  ]
}
```
