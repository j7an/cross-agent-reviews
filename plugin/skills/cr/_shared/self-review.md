# Author-Round Self-Review Checklist

Referenced by author rounds 1b / 2b / 3b. Adopted verbatim from `superpowers:subagent-driven-development/implementer-prompt.md` v5.0.7 with review-pipeline framing.

After applying each accepted finding's correction to the artifact, but before emitting the round's output JSON, self-review the correction against these four canonical checks:

1. **resolves the finding** — does the edit actually address the blocker / gap, or does it sidestep it with a superficial change?
2. **does not introduce new ambiguity** — does the new wording leave any term, reference, or invariant under-defined relative to its surroundings?
3. **does not over-specify** — does the edit add prescriptive detail beyond what the finding asked for, narrowing the design space without cause?
4. **does not create contradictions** — does the new wording conflict with any other section of the artifact, including ones not directly touched by this round?

For each accepted finding, emit a `self_review` entry in the output JSON with:

- `finding_id`: the id of the finding the correction addresses
- `resolved`: boolean — covers checklist item 1
- `over_specified`: boolean — covers checklist item 3
- `introduces_contradiction`: boolean — covers checklist item 4
- `notes`: one short sentence — only required if any of the booleans flag a concern OR if the new-ambiguity check (item 2) surfaced a residual concern that survived the fix-before-emit rule

The "does not introduce new ambiguity" check (item 2) has no dedicated boolean. It is fully covered by the fix-before-emit rule below: any ambiguity caught during self-review MUST be eliminated by re-editing the artifact before the JSON is emitted, so a clean run encodes "no ambiguity" implicitly. Only if a residual ambiguity concern remains after re-editing does it surface — in `notes`, with a one-sentence explanation.

If self-review flags an issue, fix the edit before emitting JSON. Do not ship a flagged correction expecting the next round to catch it — the next round's job is verification, not adjudication, and a flagged correction in the output erodes trust in the contract.
