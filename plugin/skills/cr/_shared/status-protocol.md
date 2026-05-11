# Reviewer-Round Status Protocol

Adopted from `superpowers:subagent-driven-development` status protocol with review-specific labels. The four-category structure and controller actions are unchanged from the source; the labels are adapted for reviewer rounds (lowercase, review-specific names) so the JSON contract stays case-distinguishable from author-round outputs (which retain the original uppercase Superpowers labels — see `status-report.md`).

This file is referenced by reviewer rounds 1a / 2a / 3a only.

## Status Categories

| Status | Meaning | Controller action |
|---|---|---|
| `findings_found` | Reviewer slice produced one or more findings | Include findings in output JSON |
| `clean` | Reviewer slice produced no findings | Mark slice clean in output JSON; emit empty findings array |
| `blocked` | Sub-agent cannot complete review at current model tier | Re-dispatch at a higher tier; if still stuck, escalate to operator |
| `needs_context` | Sub-agent is missing required input (e.g., truncated slice, unresolvable reference) | Provide the missing context, then re-dispatch |

## Aggregation Rules

- A slice with status `clean` and an empty `findings` array MUST still appear in the round's output `agents` array — emitting `[]` is the explicit signal "this slice was reviewed and produced nothing", as opposed to a missing slice which would indicate dispatch failure.
- A slice with status `findings_found` MUST have a non-empty `findings` array.
- A slice with status `blocked` (reasoning shortfall) or `needs_context` is recovered (re-dispatch) before round-level JSON is emitted; these recoverable statuses MUST NOT appear in the final round JSON. The single exception is `blocked` due to an artifact-internal contradiction the reviewer cannot adjudicate (see Escalation Decision Tree below) — that variant IS emitted at round level so the operator can repair the artifact.

## Escalation Decision Tree

- `blocked` due to reasoning shortfall → re-dispatch the same slice at a higher model tier per `model-tier-rubric.md`. Never emitted at round level.
- `blocked` due to internal contradiction in the artifact → emit at round level as `blocked` with a one-sentence explanation; the operator decides whether to repair the artifact or override. This is the one allowed `blocked` variant in final round JSON.
- `needs_context` → identify the missing input, supply it (often a clearer slice definition or a referenced section), and re-dispatch the same model. Never emitted at round level.

This protocol mirrors `subagent-driven-development/SKILL.md` § 102-118 with reviewer-specific label substitutions per spec §7.2.
